# alexa-baby-tracker
Alexa integration for [Baby Tracker](http://nighp.com/babytracker/).

This lets users say things like "tell baby tracker to record a wet diaper". This is currently unsuitable for more than one user, since information about the baby is hard coded.

## Deployment
### Lambda Function
* Set up an [OAuth Passthrough](https://github.com/sasmith/oauth-passthrough) deployment so users will be able to link their Alexa account with their Baby Tracker account. If you're planning on using this app for just yourself, you might want to just rip this part out.
* Install [PyCrypto](https://github.com/dlitz/pycrypto) to your local checkout of this code. PyCrypto contains compiled modules, so you'll need to get a version that's been compiled in an AWS version of Linux. Since PyCrypto is already installed on in AWS Linux, the easiest way to do this is just to spin up a small EC2 instance and run
```
rsync -r ec2-user@YOUR_EC2_INSTANCE_IP:/usr/lib64/python2.7/dist-packages/Crypto .
```
* Copy the private key from the OAuth Passthrough deployment into the alex-baby-tracker directory.
* Install [Requests](http://docs.python-requests.org/en/master/) to your local directory.
* Create data files for your config and your baby. These should be json files names `config.json` and `baby_data.json` respectively. They should be formatted like
```
{
    "application_id": "String" # id of your Alexa App, or null
}
```
and
```
{
{
    "dueDay": "YYYY-mm-dd HH:MM:SS +0000",
    "BCObjectType": "Baby",
    "gender": "false", # true = boy?
    "pictureName": "String",
    "dob": "YYYY-mm-dd HH:MM:SS +0000",
    "newFlage": "false", # ??
    "timestamp": "YYYY-mm-dd HH:MM:SS +0000", # Timestamp of the Baby Tracker object creation.
    "name": "String",
    "objectID": "String"
}
```
* Zip everything up and create an [AWS Lambda Function](https://aws.amazon.com/lambda/) function with the resulting zip file.

### Alexa Skill
Create an Alexa skill that points to your Lambda Function. You can do this from https://developer.amazon.com.
