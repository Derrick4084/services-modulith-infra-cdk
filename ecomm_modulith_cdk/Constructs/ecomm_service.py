from aws_cdk import (
    Duration,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager
)
from constructs import Construct
from dataclasses import dataclass



@dataclass
class EcommProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    task_role: iam.Role
    execution_role: iam.Role
    repo_secret: secretsmanager.ISecret
    pg_secret_name: str
    docdb_secret_name: str
    pg_sg_id: str
    docdb_sg_id: str
    redis_info: dict
    zipkin_info: dict
    namespace: str
    active_profile: str
    environment: str


class EcommService(Construct):
    def __init__(self, scope: Construct, id: str, props: EcommProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)

        ecomm_image = "ghcr.io/derrick4084/services-modulith:latest"
        pipeline_env = props.environment


        self.ecomm_task_def = ecs.FargateTaskDefinition(self, f"{pipeline_env}-EcommAppFargateServiceTaskDef",
                    execution_role=props.execution_role,
                    task_role=props.task_role,
                    cpu=1024,
                    memory_limit_mib=2048
            )
        self.ecomm_task_def.add_container(f"{pipeline_env}-ecomm-app-svc",
            image=ecs.ContainerImage.from_registry(ecomm_image, credentials=props.repo_secret),
            container_name=f"{pipeline_env}-ecomm-service",
            environment={    
                "POSTGRES_DB_SECRET_NAME": props.pg_secret_name,
                "DOCUMENTDB_SECRET_NAME": props.docdb_secret_name,
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx3200m -XX:+UseG1GC",
                "SPRING_PROFILES_ACTIVE": props.active_profile,
                "ZIPKIN_HOST": props.zipkin_info["zipkin-host"],
                "ZIPKIN_PORT": props.zipkin_info["zipkin-port"],
                "REDIS_HOST": props.redis_info["redis-endpoint"],
                "REDIS_PORT": props.redis_info["redis-port"]
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix=f"{pipeline_env}-ecomm-service", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8079, name=f"{pipeline_env}-ecomm-http", protocol=ecs.Protocol.TCP)],
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8079/actuator/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60)
            )
        )

        self.ecomm_service = ecs.FargateService(self, f"{pipeline_env}-EcommAppService",
            cluster=props.cluster,
            task_definition=self.ecomm_task_def,
            desired_count=2,
            assign_public_ip=False,
            service_name=f"{pipeline_env}-ecomm-service",
            enable_execute_command=True
        )
        self.ecomm_service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix=f"{pipeline_env}-ecomm-svc-connect",
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name=f"{pipeline_env}-ecomm-http",
                    dns_name="ecomm-svc",
                    port=8079,
                    discovery_name="ecomm-svc",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )

        docdb_sg = ec2.SecurityGroup.from_security_group_id(self, f"{pipeline_env}-DocDbSG", props.docdb_sg_id)
        docdb_sg.add_ingress_rule(
            peer=self.ecomm_service.connections.security_groups[0],
            connection=ec2.Port.tcp(27017),
            description="Allow Ecomm App service to access DocumentDB"
        )

        # Create security group rules for the services that need to access Postgres
        postgres_sg = ec2.SecurityGroup.from_security_group_id(self, f"{pipeline_env}-PostgresSG", props.pg_sg_id)
        postgres_sg.add_ingress_rule(
            peer=self.ecomm_service.connections.security_groups[0],
            connection=ec2.Port.tcp(5432),
            description="Allow ECS to talk to Postgres"
        )

    