import argparse
import sys
from typing import List, Optional
 
import boto3
from botocore.exceptions import ClientError
 
 
AL2023_AMI_SSM_PARAM = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
 
 
def get_ec2_clients(region: str):
    ec2 = boto3.client("ec2", region_name=region)
    ec2_res = boto3.resource("ec2", region_name=region)
    ssm = boto3.client("ssm", region_name=region)
    return ec2, ec2_res, ssm
   
 
def resolve_latest_al2023_ami(ssm) -> str:
    """Fetch the latest Amazon Linux 2023 AMI for the region."""
    resp = ssm.get_parameter(Name=AL2023_AMI_SSM_PARAM)
    return resp["Parameter"]["Value"]
 
 
def find_instances_by_name(ec2, name: str) -> List[str]:
    """Return instance IDs (non-terminated) matching the Name tag."""
    filters = [
        {"Name": "tag:Name", "Values": [name]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ]
    resp = ec2.describe_instances(Filters=filters)
    ids = []
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            ids.append(inst["InstanceId"])
    return ids
 
 
def start_action(args):
    ec2, ec2_res, ssm = get_ec2_clients(args.region)
 
    target_ids = []
    if args.instance_id:
        target_ids = [args.instance_id]
    elif args.name:
        target_ids = find_instances_by_name(ec2, args.name)
 
    try:
        if target_ids:
            # Start existing stopped instances
            to_start = []
            desc = ec2.describe_instances(InstanceIds=target_ids)
            for res in desc["Reservations"]:
                for inst in res["Instances"]:
                    state = inst["State"]["Name"]
                    if state == "stopped":
                        to_start.append(inst["InstanceId"])
                    elif state == "running":
                        print(f"[INFO] Instance {inst['InstanceId']} already running.")
 
            if to_start:
                print(f"[ACTION] Starting instance(s): {', '.join(to_start)}")
                ec2.start_instances(InstanceIds=to_start)
                waiter = ec2.get_waiter("instance_running")
                waiter.wait(InstanceIds=to_start)
                print("[OK] Instance(s) are running.")
            else:
                print("[INFO] No stopped instances to start.")
            return
 
        # Create a new instance
        ami_id = resolve_latest_al2023_ami(ssm)
 
        run_kwargs = {
            "ImageId": ami_id,
            "InstanceType": args.instance_type,     # <-- DYNAMIC INSTANCE TYPE
            "MinCount": 1,
            "MaxCount": 1,
        }
 
        if args.key_name:
            run_kwargs["KeyName"] = args.key_name
        if args.sg_ids:
            run_kwargs["SecurityGroupIds"] = args.sg_ids
        if args.subnet_id:
            run_kwargs["SubnetId"] = args.subnet_id
        if args.name:
            run_kwargs["TagSpecifications"] = [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": args.name}],
                }
            ]
 
        print(f"[ACTION] Launching {args.instance_type} with AMI {ami_id} in {args.region} ...")
        resp = ec2.run_instances(**run_kwargs)
 
        instance_id = resp["Instances"][0]["InstanceId"]
        print(f"[INFO] Launched instance: {instance_id}")
 
        waiter = ec2.get_waiter("instance_running")
        waiter.wait(InstanceIds=[instance_id])
 
        instance = ec2_res.Instance(instance_id)
        instance.load()
 
        print(f"[OK] Instance running. Public IP: {instance.public_ip_address}, "
              f"AZ: {instance.placement['AvailabilityZone']}")
 
    except ClientError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
 
 
def stop_action(args):
    ec2, _, _ = get_ec2_clients(args.region)
 
    if not args.instance_id and not args.name:
        print("[ERROR] Provide --instance-id or --name to stop.")
        sys.exit(2)
 
    try:
        target_ids = [args.instance_id] if args.instance_id else find_instances_by_name(ec2, args.name)
 
        if not target_ids:
            print(f"[INFO] No instances found with name {args.name}.")
            return
 
        print(f"[ACTION] Stopping instance(s): {', '.join(target_ids)}")
        ec2.stop_instances(InstanceIds=target_ids)
        waiter = ec2.get_waiter("instance_stopped")
        waiter.wait(InstanceIds=target_ids)
 
        print("[OK] Instance(s) stopped.")
 
    except ClientError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
 
 
def delete_action(args):
    ec2, _, _ = get_ec2_clients(args.region)
 
    if not args.instance_id and not args.name:
        print("[ERROR] Provide --instance-id or --name to delete.")
        sys.exit(2)
 
    try:
        target_ids = [args.instance_id] if args.instance_id else find_instances_by_name(ec2, args.name)
 
        if not target_ids:
            print(f"[INFO] No instances found with name {args.name}.")
            return
 
        print(f"[ACTION] Terminating instance(s): {', '.join(target_ids)}")
        ec2.terminate_instances(InstanceIds=target_ids)
        waiter = ec2.get_waiter("instance_terminated")
        waiter.wait(InstanceIds=target_ids)
 
        print("[OK] Instance(s) terminated.")
        print("[NOTE] EBS volumes with DeleteOnTermination=True removed.")
 
    except ClientError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
 
 
def parse_args(argv: Optional[list] = None):
    parser = argparse.ArgumentParser(description="Create/Start, Stop, or Delete a Linux EC2 instance.")
    parser.add_argument("action", choices=["start", "stop", "delete"], help="Action to perform.")
    parser.add_argument("--region", default="ap-south-2", help="AWS Region.")
    parser.add_argument("--name", help="Tag:Name used to find or assign to the instance.")
    parser.add_argument("--instance-id", help="Specific instance ID.")
    parser.add_argument("--key-name", help="EC2 Key Pair name.")
    parser.add_argument("--sg-ids", nargs="+", help="Security Group IDs.")
    parser.add_argument("--subnet-id", help="Subnet ID.")
    parser.add_argument("--instance-type", default="t3.micro",
                        help="EC2 instance type when creating (default: t3.micro).")
    return parser.parse_args(argv)
 
 
def main():
    args = parse_args()
 
    if args.action == "start":
        start_action(args)
    elif args.action == "stop":
        stop_action(args)
    elif args.action == "delete":
        delete_action(args)
    else:
        print("[ERROR] Invalid action.")
        sys.exit(2)
 
 
if __name__ == "__main__":
    main()
 