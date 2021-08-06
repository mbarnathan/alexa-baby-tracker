#!/usr/bin/env python
"""An Alexa skill to record dirty diapers in the Baby Tracker app.

http://nighp.com/babytracker/
"""

import base64
import datetime
import json
import uuid
from abc import ABCMeta, abstractmethod
from enum import Enum
from typing import Union, Tuple

import isodate
import requests


# Define singular values; the app will pluralize them as needed.
class Unit(Enum):
    MILLILITER = "milliliter"
    MILLILITERS = "milliliter"
    ML = "milliliter"
    OUNCE = "ounce"
    OUNCES = "ounce"
    OZ = "ounce"
    CUP = "cup"
    CUPS = "cup"


class Breast(Enum):
    LEFT = 1
    RIGHT = 2


URL = "https://prodapp.babytrackers.com"
KEY_FILENAME = "oauth_passthrough.key"
CONFIG = json.load(open("config.json"))

DEVICE_UUID = CONFIG["device_uuid"]
EMAIL = CONFIG.get("email")
PASSWORD = CONFIG.get("password")

# TODO: load this from the baby tracker server
BABY_DATA = json.load(open("baby_data.json"))
if not isinstance(BABY_DATA, list):
    BABY_DATA = [BABY_DATA]

BABY_DATA = {baby["name"].lower(): baby for baby in BABY_DATA}


def credentials_from_oauth(session) -> Tuple[str, str, str]:
    from Crypto.Cipher import PKCS1_OAEP
    from Crypto.PublicKey import RSA
    encoded_encrypted_token = session["user"].get("accessToken")
    if encoded_encrypted_token is None:
        print("No token provided.")
        return None

    try:
        encrypted_token = base64.b64decode(encoded_encrypted_token)
    except TypeError:
        print("Token incorrectly encoded.")
        return None

    key = RSA.importKey(open(KEY_FILENAME).read())
    cipher = PKCS1_OAEP.new(key)

    try:
        token = cipher.decrypt(encrypted_token)
    except ValueError:
        print("Token wasn't validly encrypted.")
        return None

    try:
        password_data = json.loads(token)
    except ValueError:
        print("Token wasn't valid json.")
        return None

    try:
        email_address = password_data["email"]
    except KeyError:
        print("Token was missing the 'email' field.")
        return None

    try:
        password = password_data["password"]
    except KeyError:
        print("Token was missing the 'password' field.")
        return None

    return email_address, password, session["application"]["applicationId"]


def login_data(email_address, password, device_uuid):
    # TODO: figure out what portion of this is required
    return {
        "Device": {
            "DeviceOSInfo": "Alexa",
            "DeviceName": "Baby Tracker Alexa App",
            "DeviceUUID": device_uuid
        },
        # TODO: I don't know what this means
        "AppInfo": {
            "AppType": 0,
            "AccountType": 0
        },
        "Password": password,
        "EmailAddress": email_address
    }


DIAPER_STATUS = {
    "wet": 0,
    "dirty": 1,
    "poopy": 1,
    "mixed": 2,
    "dry": 3
}


# Generic Alexa -- this is pretty generic Alexa boilerplate.


def lambda_handler(event, context):
    # Ensure that we're being called by the expected application.
    application_id = CONFIG["application_id"]
    if application_id is not None and (
            event["session"]["application"]["applicationId"] != application_id):
        raise ValueError("Invalid Application ID")

    if event["request"]["type"] == "IntentRequest":
        return on_intent(event["request"], event["session"])


def on_intent(intent_request, session):
    """ Called when the user specifies an intent for this skill """

    intent = intent_request["intent"]
    credentials = login_data(EMAIL, PASSWORD, DEVICE_UUID)
    if credentials is None:
        return build_response(build_link_account_response())

    try:
        return Intent.map(intent, credentials).record()
    except ValueError as e:
        print(e)
        return build_response(build_speechlet_response("Baby Tracker", "Sorry, I didn't get that."))


def build_speechlet_response(title, output, reprompt_text=None, should_end_session=True):
    result = {
        "outputSpeech": {
            "type": "PlainText",
            "text": output
        },
        "card": {
            "type": "Simple",
            # TODO: Make these more resonable for this app.
            "title": "SessionSpeechlet - " + title,
            "content": "SessionSpeechlet - " + output
        },
        "reprompt": {
            "outputSpeech": {
                "type": "PlainText",
                "text": reprompt_text
            }
        },
        "shouldEndSession": should_end_session
    }
    if reprompt_text is not None:
        result["reprompt"] = {
            "outputSpeech": {
                "type": "PlainText",
                "text": reprompt_text
            }
        }
    return result


def build_link_account_response():
    output = (
        "Your account needs to be linked to Baby Tracker. Please refer to the documentation."
    )
    return {
        "outputSpeech": {
            "type": "PlainText",
            "text": output
        },
        "card": {
            "type": "LinkAccount"
        },
        "shouldEndSession": True
    }


def build_response(response):
    # right now we don't use sessionAttributes
    return {
        "version": "1.0",
        "response": response
    }

## Baby Tracker Sync -- these functions are on the Baby Tracker side of the skill.


def _object_id() -> str:
    return str(uuid.uuid1())


def _format_time(dt: datetime.datetime = None) -> str:
    dt = dt or datetime.datetime.utcnow()
    return dt.strftime("%Y-%m-%d %H:%M:%S +0000")


def _to_timedelta(duration: Union[str, int, datetime.timedelta, isodate.Duration]) \
        -> Tuple[datetime.timedelta, int]:
    if isinstance(duration, str):
        duration = isodate.parse_duration(duration)
    elif isinstance(duration, int) or isinstance(duration, float):
        duration = datetime.timedelta(minutes=round(duration))
    return duration, round(duration.total_seconds() / 60.0)


def login(login_data_) -> requests.Session:
    session = requests.Session()
    response = session.post(URL + "/session", data=json.dumps(login_data_))
    if response.text == "Account has been reset. Please login again":
        # TODO(mb): Write persistent new UUID to storage; the old one will no longer work.
        raise PermissionError(response.text)
    return session


def generate_transaction(transaction_data, sync_id):
    return {
        "Transaction": base64.b64encode(json.dumps(transaction_data).encode("utf-8"))
                             .decode("utf-8"),
        "SyncID": sync_id,
        # This is sometimes 0, sometimes 1. Not sure if ever higher. Not sure what it's for.
        "OPCode": 0
    }


def last_sync_id(session):
    response = session.get(URL + "/account/device")
    if response.text == "Unauthorized":
        raise PermissionError("Couldn't authenticate with BabyTracker")
    devices = json.loads(response.text)
    for device in devices:
        if device["DeviceUUID"] == DEVICE_UUID:
            return device["LastSyncID"]
    return 0


class Intent(metaclass=ABCMeta):
    @abstractmethod
    def title(self):
        pass

    @abstractmethod
    def success(self, *args, **kwargs):
        pass

    @abstractmethod
    def data(self, *args, **kwargs):
        pass

    @staticmethod
    def map(intent, login_data_) -> "Intent":
        intent_name = intent["name"]
        diaper_intents = {
            "Diaper": None,
            "RecordDiaperIntent": None,
            "Pee": "wet",
            "Poo": "dirty",
            "Mixed": "mixed"
        }

        if intent_name in diaper_intents:
            return Diaper.parse(diaper_type=diaper_intents[intent_name], intent=intent,
                                credentials=login_data_)
        elif intent_name == "Formula":
            return Formula.parse(intent, login_data_)
        elif intent_name == "Nursing":
            return Nursing.parse(intent, login_data_)
        else:
            raise ValueError(f"Invalid intent: {intent_name}")

    def __init__(self, intent=None, credentials=None, baby_name=None, time=None):
        self.baby_name = baby_name or Intent._baby_from_intent(intent)
        self.credentials = credentials
        self.intent = intent
        self.time = time

    @staticmethod
    def _baby_from_intent(intent):
        baby = intent["slots"].get("Baby", {}).get("value")
        if not baby:
            if len(BABY_DATA) > 1:
                raise LookupError("Please tell me which baby")
            elif len(BABY_DATA) == 0:
                raise LookupError("No babies are set up yet. Refer to the setup instructions.")
            else:
                baby = BABY_DATA.keys()[0]
        return baby

    def record(self, *args, **kwargs):
        try:
            data = self.data(*args, **kwargs)
            with login(self.credentials) as session:
                sync_id = last_sync_id(session) + 1
                session.post(URL + "/account/transaction",
                             data=json.dumps(generate_transaction(data, sync_id)))
        except Exception as e:
            return self.say(str(e))

        return self.success(*args, **kwargs)

    def say(self, text):
        return build_response(build_speechlet_response(self.title(), text))

    def _time(self, dt=None):
        return _format_time(dt or self.time)


class Diaper(Intent):
    # noinspection PyMethodMayBeStatic
    def title(self):
        return "Record Diaper"

    def success(self):
        return self.say(f"{self.baby_name} had a {self.status} diaper.")

    def __init__(self, diaper_type: str, *args, **kwargs):
        super(Diaper, self).__init__(*args, **kwargs)
        self.status = diaper_type

    @staticmethod
    def parse(intent, credentials, diaper_type=None, *args, **kwargs):
        return Diaper(diaper_type=diaper_type or intent["slots"]["DiaperType"]["value"],
                      intent=intent, credentials=credentials, *args, **kwargs)

    def data(self, status: Union[int, str] = None):
        status = status if status is not None else self.status
        if isinstance(status, str):
            status = DIAPER_STATUS[status]

        if status is None:
            raise KeyError("Invalid diaper type")

        return {
            "BCObjectType": "Diaper",
            # These default to 5s on some apps (iPhone, I think) and 0s on others (Android?).
            # They don't seem to be used anywhere, though, so the values we set here don't
            # seem important.
            "pooColor": 0,
            "peeColor": 0,
            "note": "",
            # now
            "timestamp": self._time(),
            "newFlage": "true",
            "pictureLoaded": "true",
            # Time of diaper. We could let people provide this time, but at the moment
            # there doesn't seem like a lot of benefit.
            "time": self._time(),
            "objectID": _object_id(),
            "texture": 5,
            "amount": 2,
            "baby": BABY_DATA[self.baby_name.lower()],
            "flag": 0,
            "pictureNote": [],
            "status": status
        }


class Formula(Intent):
    def title(self):
        return "Record Formula"

    def __init__(self, amount, unit: Unit = None, *args, **kwargs):
        super(Formula, self).__init__(*args, **kwargs)
        self.amount = float(amount)
        self.unit = unit or Unit.ML

    @staticmethod
    def parse(intent, credentials, *args, **kwargs):
        unit_str = str(intent["slots"]["unit"]["value"]).upper()
        return Formula(amount=intent["slots"]["number"]["value"],
                       unit=Unit[unit_str], intent=intent, credentials=credentials, *args, **kwargs)

    def data(self):
        unit = self.unit
        amount = self.amount

        if unit == Unit.CUPS:
            unit = Unit.OZ
            amount *= 8

        return {
            "BCObjectType": "Formula",
            "amount": {
                "englishMeasure": str(unit == Unit.OZ).lower(),
                "value": amount
            },
            "baby": BABY_DATA[self.baby_name.lower()],
            "note": "",
            "pictureLoaded": "true",
            "pictureNote": [],
            "time": self._time(),
            "newFlage": "true",
            "objectID": _object_id(),
            "timestamp": self._time()
        }

    def success(self, *args, **kwargs):
        plural = "" if self.amount == 1 else "s"
        return self.say(
            f"{self.baby_name} drank {self.amount:0.3g} {self.unit.value}{plural} of formula.")


class Nursing(Intent):
    def title(self):
        return "Record Nursing"

    def __init__(self,
                 duration: Union[datetime.timedelta, int, str, isodate.Duration],
                 direction: Breast = None, *args, **kwargs):
        super(Nursing, self).__init__(*args, **kwargs)
        self.duration, self.minutes = _to_timedelta(duration)
        self.direction = direction or Breast.LEFT

    @staticmethod
    def parse(intent, credentials, *args, **kwargs):
        direction_str = intent["slots"].get("direction", {}).get("value")
        return Nursing(duration=intent["slots"]["duration"]["value"],
                       direction=Breast[direction_str.upper()] if direction_str else None,
                       intent=intent, credentials=credentials, *args, **kwargs)

    def data(self):
        duration = self.duration
        minutes = self.minutes
        breast = self.direction
        return {
            "BCObjectType": "Nursing",
            "bothDuration": minutes if breast is None else 0,
            "finishSide": breast.value if breast else "0",
            "leftDuration": minutes if breast == Breast.LEFT else 0,
            "rightDuration": minutes if breast == Breast.RIGHT else 0,
            "baby": BABY_DATA[self.baby_name.lower()],
            "note": "",
            "pictureLoaded": "true",
            "pictureNote": [],
            "time": self._time(datetime.datetime.utcnow() - duration),
            "newFlage": "true",
            "objectID": _object_id(),
            "timestamp": self._time()
        }

    def success(self, *args, **kwargs):
        plural = "" if self.duration == 1 else "s"
        direction_str = self.direction.name.lower()
        direction_speech = f" on the {direction_str}" if self.direction else ""
        return self.say(f"{self.baby_name} fed {self.minutes} minute{plural}{direction_speech}.")


if __name__ == "__main__":
    creds = login_data(EMAIL, PASSWORD, DEVICE_UUID)
    Diaper(baby_name="1", diaper_type="wet", credentials=creds).record()
    # Formula(baby_name="2", amount=1.5, unit=Unit.OZ, credentials=creds).record()
    # Nursing(baby_name="1", duration="PT7M", direction=None, credentials=creds).record()
