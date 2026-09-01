from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct


class QdrantStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, description="Ec2 instance for Qdrant vector store", **kwargs)



        self.qdrant_ec2_security_group = ec2.SecurityGroup(self, f"{environment}-QdrantSecurityGroup",
                    vpc=vpc,
                    security_group_name=f"{environment}-qdrant-ec2-sg",
                    description="Security group for qdrant EC2"
                )
        
        self.qdrant_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(22),
            description="Allow SSH access from private subnets"
        )

        self.qdrant_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(6333),
            description="Allow access to qdrant from private subnets"
        )

        self.qdrant_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(6334),
            description="Allow access to qdrant grpc from private subnets"
        )


        self.qdrant_ec2_instance = ec2.Instance(self, f"{environment}-QdrantInstance",
            instance_type=ec2.InstanceType("t3.large"),  # Choose an appropriate instance type for your model
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            instance_name=f"{environment}-qdrant",
            block_devices=[ec2.BlockDevice(
                device_name="/dev/xvda",
                volume=ec2.BlockDeviceVolume.ebs(50)  # 50 GB EBS volume
            )],
            vpc=vpc,
            security_group=self.qdrant_ec2_security_group,
            user_data=ec2.UserData.custom('''
#!/bin/bash

set -e

sudo dnf update -y
sudo dnf install -y docker

sudo systemctl enable --now docker

sudo usermod -aG docker ec2-user

# Create persistent Qdrant storage
sudo mkdir -p /home/ec2-user/qdrant_storage
sudo chown -R ec2-user:ec2-user /home/ec2-user/qdrant_storage

# Pull Qdrant
sudo -u ec2-user docker pull qdrant/qdrant

# Create Qdrant container
sudo -u ec2-user docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v /home/ec2-user/qdrant_storage:/qdrant/storage \
  --restart always \
  qdrant/qdrant''')
)

        
        CfnOutput(self, f"{environment}-QdrantInstancePort",
            value="6334",
            description="The port of the Qdrant EC2 instance"
        )

        CfnOutput(self, f"{environment}-QdrantPrivateIP",
            value=self.qdrant_ec2_instance.instance_private_ip,
            description="The private IP address of the Qdrant EC2 instance"
        )

    @property
    def qdrant_info(self) -> dict:
        return {
            "qdrant-port": "6334",
            "qdrant-host": self.qdrant_ec2_instance.instance_private_ip
        }

