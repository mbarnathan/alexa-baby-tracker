# alexa-baby-tracker
Alexa integration for [Baby Tracker](http://nighp.com/babytracker/). This version supports multiple babies (which you name in a "Baby" slot within your speech model).

This lets users say things like "tell baby tracker John peed". Information about the baby is still hard-coded, but multiple babies are supported in the config (use a JSON array).

## Deployment
### Lambda Function
* Set up an [OAuth Passthrough](https://github.com/sasmith/oauth-passthrough) deployment so users will be able to link their Alexa account with their Baby Tracker account. If you're planning on using this app for just yourself, you can also just specify an email and password in config.json.
* Install [PyCrypto](https://github.com/dlitz/pycrypto) to your local checkout of this code if you're using the oauth passthrough. If you're using a username and password, you can skip this step as the module is not required in this case. PyCrypto contains compiled modules, so you'll need to get a version that's been compiled in an AWS version of Linux. Since PyCrypto is already installed on in AWS Linux, the easiest way to do this is just to spin up a small EC2 instance and run
```
rsync -r ec2-user@YOUR_EC2_INSTANCE_IP:/usr/lib64/python2.7/dist-packages/Crypto .
```
* Copy the private key from the OAuth Passthrough deployment into the alex-baby-tracker directory, if using it.
* pip install -r requirements.txt
* Create data files for your config and your babies. These should be json files names `config.json` and `baby_data.json` respectively. They should be formatted like
```
{
    "application_id": "String", # id of your Alexa App, or null
    "email": "<your BabyTracker sync email>", # if you're using email + password login
    "password": "<your BabyTracker sync PW>", # if you're using email + password login
    "device_uuid": "<make up a UUID>" # https://www.uuidgenerator.net/
}
```
and
```
[{
    "dueDay": "YYYY-mm-dd HH:MM:SS +0000",
    "BCObjectType": "Baby",
    "gender": "false", # true = boy?
    "pictureName": "String",
    "dob": "YYYY-mm-dd HH:MM:SS +0000",
    "newFlage": "false", # ??
    "timestamp": "YYYY-mm-dd HH:MM:SS +0000", # Timestamp of the Baby Tracker object creation.
    "name": "Baby 1",
    "objectID": "String"
},
{
  # ...baby 2
},
{
  # etc., as many as you need
}]
```
* Zip everything up and create an [AWS Lambda Function](https://aws.amazon.com/lambda/) function with the resulting zip file.

### Alexa Skill
Create an Alexa skill that points to your Lambda Function. You can do this from https://developer.amazon.com.
