#!/usr/bin/env python
"""An Alexa skill to record dirty diapers in the Baby Tracker app.

http://nighp.com/babytracker/
"""

import base64
import datetime
import json
import uuid
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


## Generic Alexa -- this is pretty generic Alexa boilerplate.


def lambda_handler(event, context):
    # Ensure that we're being called by the expected application.
    application_id = CONFIG["application_id"]
    if application_id is not None and (
            event["session"]["application"]["applicationId"] != application_id):
        raise ValueError("Invalid Application ID")

    if event["request"]["type"] == "LaunchRequest":
        # TODO: Give a reasonable welcome speech.
        #return on_launch(event["request"], event["session"])
        pass
    elif event["request"]["type"] == "IntentRequest":
        return on_intent(event["request"], event["session"])


def on_intent(intent_request, session):
    """ Called when the user specifies an intent for this skill """

    intent = intent_request["intent"]
    intent_name = intent_request["intent"]["name"]

    if intent_name == "Diaper" or intent_name == "RecordDiaperIntent":
        return record_diaper_intent(intent)
    elif intent_name == "Pee":
        return record_diaper_intent(intent, "wet")
    elif intent_name == "Poo":
        return record_diaper_intent(intent, "dirty")
    elif intent_name == "Mixed":
        return record_diaper_intent(intent, "mixed")
    elif intent_name == "Formula":
        return record_formula_intent(intent)
    elif intent_name == "Nursing":
        return record_nursing_intent(intent)

    raise ValueError("Invalid intent")


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
        "Your account needs to be linked to Baby Tracker. Please use the Alexa "
        "app on your phone to do this."
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


def _time(dt: datetime.datetime = None) -> str:
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


def generate_diaper_data(baby_name, status):
    return {
        "BCObjectType": "Diaper",
        # These default to 5s on some apps (iPhone, I think) and 0s on others (Android?).
        # They don't seem to be used anywhere, though, so the values we set here don't
        # seem important.
        "pooColor": 0,
        "peeColor": 0,
        "note": "",
        # now
        "timestamp": _time(),
        "newFlage": "true",
        "pictureLoaded": "true",
        # Time of diaper. We could let people provide this time, but at the moment
        # there doesn't seem like a lot of benefit.
        "time": _time(),
        "objectID": _object_id(),
        "texture": 5,
        "amount": 2,
        "baby": BABY_DATA[baby_name.lower()],
        "flag": 0,
        "pictureNote": [],
        "status": status
    }


def generate_formula_data(baby_name: str, amount: float, unit: Unit = Unit.ML):
    if unit == Unit.CUPS:
        unit = Unit.OZ
        amount *= 8

    return {
      "BCObjectType": "Formula",
      "amount": {
        "englishMeasure": str(unit == Unit.OZ).lower(),
        "value": amount
      },
      "baby": BABY_DATA[baby_name.lower()],
      "note": "",
      "pictureLoaded": "true",
      "pictureNote": [],
      "time": _time(),
      "newFlage": "true",
      "objectID": _object_id(),
      "timestamp": _time()
    }


def generate_nursing_data(baby_name: str,
                          duration: Union[str, int, datetime.timedelta, isodate.Duration],
                          breast: Breast = None):
    duration, minutes = _to_timedelta(duration)
    return {
        "BCObjectType": "Nursing",
        "bothDuration": minutes if breast is None else 0,
        "finishSide": breast.value if breast else "0",
        "leftDuration": minutes if breast == Breast.LEFT else 0,
        "rightDuration": minutes if breast == Breast.RIGHT else 0,
        "baby": BABY_DATA[baby_name.lower()],
        "note": "",
        "pictureLoaded": "true",
        "pictureNote": [],
        "time": _time(datetime.datetime.utcnow() - duration),
        "newFlage": "true",
        "objectID": _object_id(),
        "timestamp": _time()
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


def record_diaper(baby_name: str, status: Union[int, str], login_data_):
    if status is None:
        raise KeyError("Invalid diaper type")

    if isinstance(status, str):
        status = DIAPER_STATUS[status]

    with login(login_data_) as session:
        sync_id = last_sync_id(session) + 1
        session.post(URL + "/account/transaction",
                     data=json.dumps(generate_transaction(generate_diaper_data(baby_name, status), sync_id)))


def record_formula(baby_name: str, amount: float, unit: Unit, login_data_):
    formula_data = generate_formula_data(baby_name, amount, unit)
    with login(login_data_) as session:
        sync_id = last_sync_id(session) + 1
        session.post(URL + "/account/transaction",
                     data=json.dumps(generate_transaction(formula_data, sync_id)))


def record_nursing(baby_name: str,
                   duration: Union[str, int, datetime.timedelta, isodate.Duration],
                   breast: Breast,
                   login_data_):
    nursing_data = generate_nursing_data(baby_name, duration, breast)
    with login(login_data_) as session:
        sync_id = last_sync_id(session) + 1
        session.post(URL + "/account/transaction",
                     data=json.dumps(generate_transaction(nursing_data, sync_id)))


# Intents -- these are somewhere between being on the Alexa side and being on the Baby Tracker side
def record_diaper_intent(intent, diaper_type: Union[int, str] = None):
    baby = intent["slots"]["Baby"]["value"]
    diaper_type = diaper_type or intent["slots"]["DiaperType"]["value"]
    login_data_ = login_data(EMAIL, PASSWORD, DEVICE_UUID)
    if login_data_ is None:
        return build_response(build_link_account_response())
    record_diaper(baby, diaper_type, login_data_)
    return build_response(build_speechlet_response(
        "Record Diaper", f"{baby} had a {diaper_type} diaper."))


def record_formula_intent(intent):
    baby = intent["slots"]["Baby"]["value"]
    amount = float(intent["slots"]["number"]["value"])
    unit_str = str(intent["slots"]["unit"]["value"]).upper()
    unit = Unit[unit_str]
    login_data_ = login_data(EMAIL, PASSWORD, DEVICE_UUID)
    if login_data_ is None:
        return build_response(build_link_account_response())
    record_formula(baby, amount, unit, login_data_)
    plural = "" if amount == 1 else "s"
    return build_response(build_speechlet_response(
        "Record Formula", f"{baby} drank {amount:0.3g} {unit.value}{plural} of formula."))


def record_nursing_intent(intent):
    baby = intent["slots"]["Baby"]["value"]
    duration, minutes = _to_timedelta(intent["slots"]["duration"]["value"])
    direction_str = str(intent["slots"]["direction"]["value"]).upper()
    direction = Breast[direction_str]
    direction_speech = f" on the {direction_str}" if direction else ""
    login_data_ = login_data(EMAIL, PASSWORD, DEVICE_UUID)
    if login_data_ is None:
        return build_response(build_link_account_response())
    record_nursing(baby, duration, direction, login_data_)
    plural = "" if duration == 1 else "s"
    return build_response(build_speechlet_response(
        "Record Nursing", f"{baby} fed {minutes} minute{plural}{direction_speech}."))


if __name__ == "__main__":
    record_diaper("2", 0, login_data(EMAIL, PASSWORD, DEVICE_UUID))
    # record_formula("2", 1.5, Unit.OZ, login_data(EMAIL, PASSWORD, DEVICE_UUID))
    # record_nursing("1", "PT5M", Breast.RIGHT, login_data(EMAIL, PASSWORD, DEVICE_UUID))

