# EC2 Management Using Python

This project contains a Python script that can start, stop, and delete
an AWS EC2 t2.micro Linux instance using the boto3 library.

## Prerequisites
- AWS CLI configured
- Python 3 installed
- boto3 installed (`pip install boto3`)
- IAM user with EC2 permissions

## Usage

Start EC2 instance:
python manage_ec2.py start

Stop EC2 instance:
python manage_ec2.py stop

Delete EC2 instance:
python manage_ec2.py delete