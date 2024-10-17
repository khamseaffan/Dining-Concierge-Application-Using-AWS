from datetime import datetime
import json
import os
import re
import time
import logging
from uuid import uuid4
import dateutil.parser
import boto3

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
QUEUE_URL = os.environ.get('QUEUE_URL')

def close_request(session_attributes, intent_name, message):
    logger.debug(f"Closing {intent_name}")
    
    response = {
        'sessionState': {
            'sessionAttributes': session_attributes,
            'dialogAction': {
                'type': 'Close'
            },
            'intent': {
                'name': intent_name,
                'state': "Fulfilled"
            },
        },
        'messages': [
            {
                "contentType": "PlainText",
                "content": message
            }
        ]
    }

    return response

def elicit_slot(session_attributes, intent_name, slots, slot_to_elicit, message):
    response = {
        'sessionState': {
            'sessionAttributes': session_attributes,
            'dialogAction': {
                'type': 'ElicitSlot',
                'slotToElicit': slot_to_elicit,
            },
            'intent': {
                'name': intent_name,
                "slots": slots,
            }
        },
        'messages': [
            message
        ]
    }
    return response

def delegate(session_attributes, slots, intent_name):
    return {
        "sessionState": {
            'sessionAttributes': session_attributes,
            'dialogAction': {
                'type': 'Delegate',
            },
            "intent": {
                "name": intent_name,
                "slots": slots,
                "state": "ReadyForFulfillment",
            }
        }
    }


def sqs_send(dinning_details):
    try:    
        sqs = boto3.client('sqs', region_name='us-east-1')
        result = sqs.send_message(
            QueueUrl=os.environ.get('QUEUE_URL'),
            MessageBody=json.dumps(dinning_details)
        )
    
        logger.info(f"SQS response: {result}")
        return True
    
    except Exception as err:
        logger.error(f"Error sending to SQS: {err}")
        return False
    
def build_validation_result(isvalid, violated_slot, message_content):
    return {
        'isValid': isvalid,
        'violatedSlot': violated_slot,
        'message': message_content
    }
    
def is_valid_location(city):
    valid_cities = ['new york', 'manhattan', 'brooklyn', 'nyc']
    return city.lower() in valid_cities


def is_valid_cuisine(cuisine):
    valid_cuisines = ['indian', 'desi', 'american', 'vegetarian', 'seafood', 'chinese', 'korean',
                      'mexican', 'mediterranean', 'vegan']
    return cuisine.lower() in valid_cuisines
    
def is_valid_date(date):
    try:
        dateutil.parser.parse(date)
        return True
    except ValueError:
        return False
        
def is_valid_email(email):
    email_regex = r"[^@]+@[^@]+\.[^@]+"
    if not re.match(email_regex, email):
        return False
    else:
        return True

def validate_slots(slots: dict) -> dict:
    # Extracting slots with the exact names used in Lex Console
    city = slots.get('location', None)
    cuisine = slots.get('cuisine', None)
    reservation_date = slots.get('reservationDate', None)
    reservation_time = slots.get('reservationTime', None)
    number_of_people = slots.get('numberOfPeople', None)
    email = slots.get('email', None)
    phone_number = slots.get('phone_number', None)

    # Validating city
    if city and not is_valid_location(city['value']['interpretedValue']):
        return build_validation_result(
            False,
            "location",
            f"We currently do not support { city['value']['interpretedValue'] }. We only support New York (New York, Manhattan, Brooklyn) region. Which location do you want to book for?"
        )

    # Validating cuisine
    if cuisine and not is_valid_cuisine(cuisine['value']['interpretedValue']):
        return build_validation_result(
            False,
            "cuisine",
            f"We currently do not offer { cuisine['value']['interpretedValue'] } cuisine. Can you try a different one?"
        )

    # Validating reservation date
    if reservation_date:
        reservation_date_value = reservation_date['value']['interpretedValue']
        if not is_valid_date(reservation_date_value):
            return build_validation_result(
                False,
                'reservationDate',
                'Please enter a valid reservation date. When would you like to make your reservation?'
            )
        if datetime.strptime(reservation_date_value, '%Y-%m-%d').date() <= datetime.now().date():
            return build_validation_result(
                False,
                'reservationDate',
                'The reservation date must be in the future. Can you please provide a future date for your reservation?'
            )

    # Validating reservation time
    if reservation_time:
        # You may add validation for the time if needed.
        pass

    # Validating number of people
    if number_of_people is not None and (int(number_of_people['value']['interpretedValue']) < 1 or int(number_of_people['value']['interpretedValue']) > 10):
        return build_validation_result(
            False,
            'numberOfPeople',
            'We accept reservations for up to 10 guests only. How many guests will be attending?'
        )

    # Validating email
    if email is not None and not is_valid_email(email['value']['interpretedValue']):
        return build_validation_result(
            False,
            'email',
            'Please provide a valid email address.'
        )

    return {'isValid': True}



def dining_suggestion(intent):
    intent_name = intent['sessionState']['intent']['name']
    logger.info("In dining_suggestion")

    logger.debug(f"Received DiningSuggestionsIntent with the following request details:\n{ json.dumps(intent) }")
    slots = intent["sessionState"]["intent"]["slots"]
    session_attributes = intent.get('sessionAttributes') if intent.get('sessionAttributes') is not None else {}
    
    dinning_details = {
        'ReservationType': 'Dining',
        'location': slots.get('location', None),
        'Cuisine': slots.get('cuisine', None),
        'DiningTime': slots.get('reservationTime', None),
        'DiningDate': slots.get('reservationDate', None),
        'NumberofPeople': slots.get('numberOfPeople', None),
        'Email': slots.get('email', None),
        'PhoneNumber': slots.get('phone_number', None)
    }
    
    if intent['invocationSource'] == 'DialogCodeHook':
        result = validate_slots(intent['sessionState']['intent']['slots'])
        if not result['isValid']:
            violated_slot = result['violatedSlot']
            slots[violated_slot] = None
            return elicit_slot(
                session_attributes,
                intent_name,
                slots,
                violated_slot,
                {
                    "contentType": "PlainText",
                    "content": result['message']
                },
            )

        return delegate(session_attributes, slots, intent_name)
    
    elif intent['invocationSource'] == "FulfillmentCodeHook":
        
        sqs_result = sqs_send(dinning_details)
        if sqs_result:
            message = "You’re all set. Expect my suggestions shortly! Have a good day."
        else:
            message = "Sorry, we are facing some issues. Please try again later."
        
        return close_request(session_attributes, intent_name, message)

def greeting_intent(intent):
    intent_name = intent['sessionState']['intent']['name']
    logger.info("In greeting_intent")
    
    session_attributes = intent.get('sessionAttributes') if intent.get(
        'sessionAttributes') is not None else {}
    
    message = {
        'contentType': 'PlainText',
        'content': 'Hi there, I am your Dining Concierge Bot. How can I help you today? You can ask for restaurant suggestions or specify any cuisine you like!'
    }
    
    return elicit_slot(
        session_attributes,
        intent_name,
        intent['sessionState']['intent']['slots'],
        None,  # No specific slot to elicit, just an open-ended prompt to guide user
        message
    )


def thankyou_intent(intent):
    intent_name = intent['sessionState']['intent']['name']
    logger.info("In thankyou_intent")

    session_attributes = intent.get('sessionAttributes') if intent.get(
        'sessionAttributes') is not None else {}
    
    message = "Thank you for using Dining Concierge Bot. How can I help you next time?"
    
    return close_request(session_attributes, intent_name, message)


def dispatch(event):
    intent_name = event['sessionState']['intent']['name']
    logger.debug(f'Intent Name: {intent_name}')

    if intent_name == 'DiningSuggestionsIntent':
        response = dining_suggestion(event)
        logger.debug(f'Intent Name: {intent_name}')
        return response
    elif intent_name =='GreetingIntent':
        return greeting_intent(event)

    elif intent_name =='ThankYouIntent':
        return thankyou_intent(event)


def lambda_handler(event, context):
    # TODO implement
    
    logger.debug('event.bot.name={}'.format(event['bot']['name']))
    logger.info(event)
    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    return dispatch(event)
    
