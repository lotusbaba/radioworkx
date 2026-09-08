import json
import os
from functools import lru_cache
import boto3
from botocore.config import Config
from app.config import ENDPOINT

@lru_cache
def client():
    return boto3.client('sqs', endpoint_url=ENDPOINT,
                        region_name=os.getenv('AWS_DEFAULT_REGION','us-east-1'),
                        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID','test'),
                        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY','test'),
                        config=Config(connect_timeout=5,read_timeout=30,retries={'max_attempts':3}))

@lru_cache
def queue(name):
    sqs = client()
    dlq = sqs.create_queue(QueueName=f'{os.getenv("QUEUE_PREFIX","radio")}-{name}-dead')['QueueUrl']
    arn = sqs.get_queue_attributes(QueueUrl=dlq,AttributeNames=['QueueArn'])['Attributes']['QueueArn']
    return sqs.create_queue(QueueName=f'{os.getenv("QUEUE_PREFIX","radio")}-{name}',Attributes={
        'VisibilityTimeout':'900' if name != 'reactions' else '60',
        'MessageRetentionPeriod':'1209600',
        'RedrivePolicy':json.dumps({'deadLetterTargetArn':arn,'maxReceiveCount':'5'})
    })['QueueUrl']

def send(name, id, body):
    attrs = {'event_id': {'DataType':'String','StringValue':id}}
    if name == 'reactions':
        attrs['genre'] = {'DataType':'String','StringValue':body['genre']}
        attrs['artist'] = {'DataType':'String','StringValue':', '.join(body['artists'])}
    client().send_message(QueueUrl=queue(name), MessageBody=json.dumps({'id':id,**body}),MessageAttributes=attrs)
