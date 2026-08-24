from aws_cdk import (
    Duration,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    Size,
    aws_secretsmanager as secretsmanager
)
from constructs import Construct
from dataclasses import dataclass


@dataclass
class RedisProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    execution_role: iam.Role
    namespace: str

class RedisService(Construct):
    def __init__(self, scope: Construct, id: str, props: RedisProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)




        redis_volume = ecs.ServiceManagedVolume(
            scope=self,
            id="RedisDataVolume",
            name="redis-data",
            managed_ebs_volume=ecs.ServiceManagedEBSVolumeConfiguration(
                size=Size.gibibytes(20),  # Size in GiB
                iops=3000,  # IOPS for the volume  # Throughput in MiB/s
                throughput=125,  # Throughput in MiB/s
                volume_type=ec2.EbsDeviceVolumeType.GP3,  # Volume type
                encrypted=True 
            )
        )

        self.redis_task_def = ecs.FargateTaskDefinition(self, "RedisTaskDef",
            cpu=1024,
            memory_limit_mib=2048,
            execution_role=props.execution_role
        )
        self.redis_task_def.add_container("redis",
            image=ecs.ContainerImage.from_registry("redis:latest"),
            container_name="redis_server",
            environment={
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx1536m -XX:+UseG1GC"
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="redis", log_retention=logs.RetentionDays.ONE_DAY),
            port_mappings=[
                ecs.PortMapping(container_port=6379, name="http", protocol=ecs.Protocol.TCP)
            ]
        )

        self.redis_service = ecs.FargateService(
            self, "RedisService",
            cluster=props.cluster,
            desired_count=1,
            service_name="redis",
            task_definition=self.redis_task_def,
            assign_public_ip=False,
            enable_execute_command=True,
            volume_configurations=[redis_volume]
        )

        self.redis_service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix="redis-connect", 
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name="http", 
                    dns_name="redis",
                    port=6379,
                    discovery_name="redis",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )

                                          

        
        