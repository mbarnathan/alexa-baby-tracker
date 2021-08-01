#!/usr/bin/env python
"""An Alexa skill to record dirty diapers in the Baby Tracker app.

http://nighp.com/babytracker/
"""

import base64
import datetime
import json
import uuid
import isodate
from enum import Enum

import requests
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA
from typing import Union

from isodate import Duration


class Unit(Enum):
    ML = 0,
    OZ = 1,
    CUPS = 2


class Breast(Enum):
    LEFT = 1,
    RIGHT = 2


URL = "https://prodapp.babytrackers.com"
KEY_FILENAME = "oauth_passthrough.key"

CONFIG = json.load(open("config.json"))
assert set(CONFIG.keys()) == {"application_id"}

# TODO: load this from the baby tracker server
BABY_DATA = json.load(open("baby_data.json"))
assert set(BABY_DATA.keys()) == {
    "dueDay",
    "BCObjectType",
    "gender",
    "pictureName",
    "dob",
    "newFlage",
    "timestamp",
    "name",
    "objectID",
}

def login_data(session):
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

    # TODO: figure out what portion of this is required
    return {
        "Device": {
            "DeviceOSInfo": "Alexa",
            "DeviceName": "Baby Tracker Alexa App",
            "DeviceUUID": session["application"]["applicationId"]
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
        return record_diaper_intent(intent, session)
    elif intent_name == "Pee":
        pass
    elif intent_name == "Poo":
        pass
    elif intent_name == "Formula":
        pass
    elif intent_name == "Nursing":
        pass

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


def generate_diaper_data(status):
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
        "baby": BABY_DATA,
        "flag": 0,
        "pictureNote": [],
        "status": status
    }


def generate_diaper_sync_data(status, sync_id):
    return {
        "Transaction": base64.b64encode(json.dumps(generate_diaper_data(status))),
        "SyncID": sync_id,
        # This is sometimes 0, sometimes 1. Not sure if ever higher. Not sure what it's for.
        "OPCode": 0
    }


def generate_formula_data(amount: float, unit: Unit = Unit.ML):
    if unit == Unit.CUPS:
        unit = Unit.OZ
        amount *= 8

    return {
      "BCObjectType": "Formula",
      "amount": {
        "englishMeasure": str(unit == Unit.OZ).lower(),
        "value": amount
      },
      "baby": BABY_DATA,
      "note": "",
      "pictureLoaded": "true",
      "pictureNote": [],
      "time": _time(),
      "newFlage": "true",
      "objectID": _object_id(),
      "timestamp": _time()
    }


def generate_nursing_data(duration: Union[str, int, datetime.timedelta, Duration],
                          breast: Breast = None):
    if isinstance(duration, str):
        duration = isodate.parse_duration(duration)
    elif isinstance(duration, int) or isinstance(duration, float):
        duration = datetime.timedelta(minutes=round(duration))

    minutes = duration.total_seconds() / 60.0
    return {
        "BCObjectType": "Nursing",
        "bothDuration": minutes if breast is None else 0,
        "finishSide": breast.value if breast else "0",
        "leftDuration": minutes if breast == Breast.LEFT else 0,
        "rightDuration": minutes if breast == Breast.RIGHT else 0,
        "baby": BABY_DATA,
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
    devices = json.loads(response.text)
    for device in devices:
        if device["DeviceUUID"] == session["application"]["applicationId"]:
            return device["LastSyncID"]
    return 0

def record_diaper(status, login_data_):
    session = requests.Session()
    # TODO: validate that we successfully connected.
    r = session.post(URL + "/session", data=json.dumps(login_data_))
    sync_id = last_sync_id(session) + 1
    session.post(URL + "/account/transaction", data=json.dumps(generate_diaper_sync_data(status, sync_id)))

## Intents -- these are somewhere between being on the Alexa side and being on the Baby Tracker side

def record_diaper_intent(intent, session):
    diaper_type = intent["slots"]["DiaperType"]["value"]
    login_data_ = login_data(session)
    if login_data_ is None:
        return build_response(build_link_account_response())
    record_diaper(DIAPER_STATUS[diaper_type], login_data_)
    return build_response(build_speechlet_response(
        "Record Diaper", "{} diaper recorded.".format(diaper_type)))


if __name__ == "__main__":
    # record a wet diaper
    record_diaper(0)
