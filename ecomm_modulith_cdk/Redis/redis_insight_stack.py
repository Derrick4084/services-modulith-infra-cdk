from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct

class RedisInsightStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, environment: str, redis_info: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        self.vpc = vpc
        self.pipeline_env = environment


        self.redis_insight_sg = ec2.SecurityGroup(
            self, f"{self.pipeline_env}-RedisInsightSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"{self.pipeline_env}-redis-insight-sg",
            description="Security group for Redis insights"
        )
        self.redis_insight_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(5540),
            description="Allow inbound traffic on port 6379"
        )


        self.redis_insight_instance = ec2.Instance(self, f"{environment}-RedisInsightInstance",
            instance_type=ec2.InstanceType("t3.large"),  # Choose an appropriate instance type for your model
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            instance_name=f"{environment}-redis-insight",
            block_devices=[ec2.BlockDevice(
                device_name="/dev/xvda",
                volume=ec2.BlockDeviceVolume.ebs(50)  # 50 GB EBS volume
            )],
            vpc=vpc,
            security_group=self.redis_insight_sg,
            user_data=ec2.UserData.custom(f'''
#!/bin/bash

set -e

sudo dnf update -y
sudo dnf install -y docker

sudo systemctl enable --now docker

sudo usermod -aG docker ec2-user

# Create persistent insight storage
sudo mkdir -p /home/ec2-user/insight_storage
sudo chown -R ec2-user:ec2-user /home/ec2-user/insight_storage

export RI_REDIS_HOST='{redis_info["redis-endpoint"]}'

# Pull Redis Insights
sudo -u ec2-user docker pull redis-insight:latest

# Create Redis insights container
sudo -u ec2-user docker run -d \
  --name redis-insight \
  -p 5540:5540 \
  -e RI_REDIS_HOST=$RI_REDIS_HOST \
  -v /home/ec2-user/insight_storage:/insight/storage \
  --restart always \
  redis/redisinsight:latest''')
)

        CfnOutput(self, f"{environment}-InsightInstancePort",
            value="5540",
            description="The port of the Insight EC2 instance"
        )

        CfnOutput(self, f"{environment}-InsightPrivateIP",
            value=self.redis_insight_instance.instance_private_ip,
            description="The private IP address of the Insight EC2 instance"
        )

    @property
    def insight_info(self) -> dict:
        return {
            "insight-port": "5540",
            "insight-host": self.redis_insight_instance.instance_private_ip
        }


        