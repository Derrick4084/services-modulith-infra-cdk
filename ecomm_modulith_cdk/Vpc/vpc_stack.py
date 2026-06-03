from aws_cdk import (
    aws_ec2 as ec2,
    Stack
    
)
from constructs import Construct


class VpcStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, description="VPC for microservice architecture", **kwargs)

        # Create a VPC with default settings
        self.vpc = ec2.Vpc(self, "MonolithVpc",
            max_azs=2,
            nat_gateways=1,
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            vpc_name="monolith-vpc",
            enable_dns_hostnames=True,
            enable_dns_support=True,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                )
            ]
        )
               
    @property
    def get_vpc(self) -> ec2.Vpc:
        return self.vpc