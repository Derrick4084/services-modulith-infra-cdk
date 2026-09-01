from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
    Token,
    RemovalPolicy
)
from constructs import Construct

class RedisClusterStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        self.vpc = vpc
        self.pipeline_env = environment


        self.redis_sg = ec2.SecurityGroup(
            self, f"{self.pipeline_env}-RedisSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"{self.pipeline_env}-redis-sg",
            description="Security group for Redis cache"
        )
        self.redis_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(6379),
            description="Allow inbound traffic on port 6379"
        )

        private_subnet_ids = [
            subnet.subnet_id for subnet in self.vpc.private_subnets
        ]

        if not private_subnet_ids:
            private_subnet_ids = [
                subnet.subnet_id for subnet in self.vpc.isolated_subnets
            ]

        redis_subnet_group = elasticache.CfnSubnetGroup(
            self, f"{self.pipeline_env}-RedisSubnetGroup",
            description="Subnet group for Redis cache",
            subnet_ids=private_subnet_ids,
            cache_subnet_group_name=f"{self.pipeline_env}-redis-subnet-group"
        )

        self.redis_cluster = elasticache.CfnReplicationGroup(
            self, f"{self.pipeline_env}-RedisCluster",
            replication_group_description=f"{self.pipeline_env}-Redis replication group",
            cache_node_type="cache.t3.micro",
            engine="redis",
            engine_version="7.1",
            port=6379,
            cache_subnet_group_name=redis_subnet_group.cache_subnet_group_name,
            security_group_ids=[self.redis_sg.security_group_id],

            automatic_failover_enabled=True,
            multi_az_enabled=True,
            num_cache_clusters=2,

            # parameter_group_name="default.redis6.x",
            # replication_group_id="redis-cluster",
            # snapshot_retention_limit=7,
            # snapshot_window="05:00-06:00",
            # preferred_maintenance_window="sun:06:00-sun:07:00",
            at_rest_encryption_enabled=True,
            transit_encryption_enabled=True,
            
        )
        self.redis_cluster.apply_removal_policy(RemovalPolicy.DESTROY)

    @property
    def redis_info(self) -> dict:
        return {
            "redis-endpoint": Token.as_string(self.redis_cluster.attr_primary_end_point),
            "redis-port": Token.as_string(self.redis_cluster.attr_primary_end_point_port),
            "redis-sg-id": self.redis_sg.security_group_id
        }


