from aws_cdk import (
    Duration,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
    Size
    
)
from constructs import Construct
from dataclasses import dataclass



@dataclass
class QdrantProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    execution_role: iam.Role
    namespace: str


class QdrantService(Construct):
    def __init__(self, scope: Construct, id: str, props: QdrantProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)

        qdrant_volume = ecs.ServiceManagedVolume(self, "QdrantVolume",
            name="qdrant-data-volume",
            managed_ebs_volume=ecs.ServiceManagedEBSVolumeConfiguration(
                size=Size.gibibytes(20),  # Size in GiB
                iops=3000,  # IOPS for the volume  # Throughput in MiB/s
                throughput=125,  # Throughput in MiB/s
                volume_type=ec2.EbsDeviceVolumeType.GP3,  # Volume type
                encrypted=True  
            )
        )

        self.qdrant_task_def = ecs.FargateTaskDefinition(self, "QdrantServiceTaskDef",
                    execution_role=props.execution_role,
                    cpu=1024,
                    memory_limit_mib=2048
                )
          
        self.qdrant_task_def.add_container("qdrant-service",
            image=ecs.ContainerImage.from_registry("qdrant/qdrant"),
            container_name="qdrant-service",
            environment={
                "QDRANT__SERVICE__GRPC_PORT": "6334",
                "QDRANT__SERVICE__HTTP_PORT": "6333"
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="qdrant-service", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[
                ecs.PortMapping(container_port=6333, name="qdrant-http", protocol=ecs.Protocol.TCP),
                ecs.PortMapping(container_port=6334, name="qdrant-grpc", protocol=ecs.Protocol.TCP)
            ]
        )
        self.qdrant_service = ecs.FargateService(self, "QdrantService",
            cluster=props.cluster,
            task_definition=self.qdrant_task_def,
            desired_count=1,
            assign_public_ip=False,
            service_name="qdrant-service",
            enable_execute_command=True,
            volume_configurations=[qdrant_volume]
        )
        self.qdrant_service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix="qdrant-service-connect", 
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name="qdrant-http", 
                    dns_name="qdrant-service",
                    port=6333,
                    discovery_name="qdrant-service",
                    idle_timeout=Duration.hours(1)
                ),
                ecs.ServiceConnectService(
                    port_mapping_name="qdrant-grpc", 
                    dns_name="qdrant-service-grpc",
                    port=6334,
                    discovery_name="qdrant-service-grpc",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )