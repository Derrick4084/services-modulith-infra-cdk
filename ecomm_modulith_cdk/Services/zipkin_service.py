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
class ZipkinProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    execution_role: iam.Role
    namespace: str

class ZipkinService(Construct):
    def __init__(self, scope: Construct, id: str, props: ZipkinProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)

        # self.zipkin_volume = ecs.ServiceManagedVolume(self, "ZipkinVolume",
        #             name="zipkin-data",
        #             managed_ebs_volume=ecs.ServiceManagedEBSVolumeConfiguration(
        #                 size=Size.gibibytes(20),  # Size in GiB
        #                 iops=3000,  # IOPS for the volume  # Throughput in MiB/s
        #                 throughput=125,  # Throughput in MiB/s
        #                 volume_type=ec2.EbsDeviceVolumeType.GP3,  # Volume type
        #                 encrypted=True  
        #             )
        #         )

        self.zipkin_task_def = ecs.FargateTaskDefinition(self, "ZipkinServiceTaskDef",
            cpu=1024,
            memory_limit_mib=2048,
            execution_role=props.execution_role
        )
        self.zipkin_task_def.add_container("zipkin",
            image=ecs.ContainerImage.from_registry("openzipkin/zipkin"),
            container_name="zipkin",
            environment={
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx1536m -XX:+UseG1GC"
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="zipkin", log_retention=logs.RetentionDays.ONE_DAY),
            port_mappings=[
                ecs.PortMapping(container_port=9411, name="http", protocol=ecs.Protocol.TCP)
            ]
        )
        self.zipkin_service = ecs_patterns.ApplicationLoadBalancedFargateService(self, "ZipkinService",
            cluster=props.cluster,
            desired_count=1,
            public_load_balancer=True,
            service_name="zipkin",
            load_balancer_name="micro-zipkin-lb",
            protocol=elbv2.ApplicationProtocol.HTTP,
            task_definition=self.zipkin_task_def,
            health_check_grace_period=Duration.seconds(60),
            enable_execute_command=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True)
        )
        self.zipkin_service.target_group.configure_health_check(
            path="/zipkin",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=5
        )
        # self.zipkin_service.task_definition.add_volume(
        #     name="zipkin-data-volume",
        #     efs_volume_configuration=ecs.EfsVolumeConfiguration(
        #         file_system_id=self.zipkin_volume.node.,
        #         transit_encryption="ENABLED"
        #     )
        # )

        self.zipkin_service.service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix="zipkin-connect", 
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name="http", 
                    dns_name="zipkin",
                    port=9411,
                    discovery_name="zipkin",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )