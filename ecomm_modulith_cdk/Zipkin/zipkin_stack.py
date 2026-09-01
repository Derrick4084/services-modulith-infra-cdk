from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct


class ZipkinStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, description="Ec2 instance for Zipkin", **kwargs)



        self.zipkin_ec2_security_group = ec2.SecurityGroup(self, f"{environment}-ZipkinSecurityGroup",
                    vpc=vpc,
                    security_group_name=f"{environment}-zipkin-ec2-sg",
                    description="Security group for zipkin EC2"
                )
        
        self.zipkin_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(22),
            description="Allow SSH access from private subnets"
        )

        self.zipkin_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(9411),
            description="Allow access zipkin from private subnets"
        )


        self.zipkin_ec2_instance = ec2.Instance(self, f"{environment}-ZipkinInstance",
                    instance_type=ec2.InstanceType("t3.large"),  # Choose an appropriate instance type for your model
                    machine_image=ec2.MachineImage.latest_amazon_linux2023(),
                    instance_name=f"{environment}-zipkin",
                    block_devices=[ec2.BlockDevice(
                        device_name="/dev/xvda",
                        volume=ec2.BlockDeviceVolume.ebs(50)  # 50 GB EBS volume
                    )],
                    vpc=vpc,
                    security_group=self.zipkin_ec2_security_group,
                    user_data=ec2.UserData.custom('''
#!/bin/bash

set -e

sudo dnf update -y
sudo dnf install -y docker

sudo systemctl enable --now docker

sudo usermod -aG docker ec2-user

# Create persistent Zipkin storage
sudo mkdir -p /home/ec2-user/zipkin_storage
sudo chown -R ec2-user:ec2-user /home/ec2-user/zipkin_storage

# Pull Zipkin
sudo -u ec2-user docker pull openzipkin/zipkin

# Create Zipkin container
sudo -u ec2-user docker run -d \
    --name zipkin \
    -p 9411:9411 \
    -v /home/ec2-user/zipkin_storage:/zipkin/storage \
    --restart always \
    openzipkin/zipkin''')
)
                       
        CfnOutput(self, f"{environment}-ZipkinInstancePort",
            value="9411",
            description="The port of the Zipkin EC2 instance"
        )

        CfnOutput(self, f"{environment}-ZipkinPrivateIP",
            value=self.zipkin_ec2_instance.instance_private_ip,
            description="The private IP address of the Zipkin EC2 instance"
        )

    @property
    def zipkin_info(self) -> dict:
        return {
            "zipkin-port": "9411",
            "zipkin-host": self.zipkin_ec2_instance.instance_private_ip
        }

        