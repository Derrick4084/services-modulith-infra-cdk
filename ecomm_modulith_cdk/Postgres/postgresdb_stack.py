from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_ec2 as ec2,
    CfnOutput,
    aws_rds as rds,
)
from constructs import Construct


class PostgresDBStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, description="PostgreSQL cluster for order, payment and product microservices", **kwargs)

        
        self.vpc = vpc

        # Create a Security Group for the PostgreSQL Database
        self.postgres_sg = ec2.SecurityGroup(self, f"{environment}-PostgresSG", 
            vpc=self.vpc,
            description="Security group for PostgreSQL database",
            security_group_name=f"{environment}-PostgresDBSG"
        )
        
        # Add Ingress Rule to allow connections to the PostgreSQL Database from anywhere
        # TODO: Restrict this to specific IP ranges or VPC CIDR blocks
        # WARNING: This is not recommended for production environments
        self.postgres_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(5432),
            description="Allow PostgreSQL access from anywhere"
        )

        # Create an Aurora PostgreSQL Cluster
        self.postgres_db_cluster = rds.DatabaseCluster(self, f"{environment}-PostgresDBCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version=rds.AuroraPostgresEngineVersion.VER_15_8),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=2,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[self.postgres_sg],
            default_database_name=f"{environment}-monolithservices",
            removal_policy=RemovalPolicy.DESTROY,
            cluster_identifier=f"{environment}-postgres-cluster",
            credentials=rds.Credentials.from_generated_secret("postgres"),
            storage_encrypted=True,
            enable_data_api=True
        )

        CfnOutput(self, f"{environment}-ClusterEndpoint", value=self.postgres_db_cluster.cluster_endpoint.hostname)
        CfnOutput(self, f"{environment}-SecretName", value=self.postgres_db_cluster.secret.secret_name)


    @property
    def postgres_info(self) -> dict:
        return {
            "secret-name": self.postgres_db_cluster.secret.secret_name,
            "security-group-id": self.postgres_sg.security_group_id
        }
