from aws_cdk import (
    Duration,
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
class McpProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    task_role: iam.Role
    execution_role: iam.Role
    repo_secret: secretsmanager.ISecret
    weather_secret_name: str
    namespace: str
    qdrant_info: dict
    zipkin_info: dict
    active_profile: str
    environment: str


class McpService(Construct):
    def __init__(self, scope: Construct, id: str, props: McpProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)


        mcp_image = "ghcr.io/derrick4084/spring-ai-mcp:latest"
        pipeline_env = props.environment


        self.mcp_task_def = ecs.FargateTaskDefinition(self, f"{pipeline_env}-McpServiceTaskDef",
                    execution_role=props.execution_role,
                    task_role=props.task_role,
                    cpu=1024,
                    memory_limit_mib=2048
                )
        self.mcp_task_def.add_container(f"{pipeline_env}-Mcp",
            image=ecs.ContainerImage.from_registry(mcp_image, credentials=props.repo_secret),
            container_name=f"{pipeline_env}-mcp-server",
            environment={
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx1536m -XX:+UseG1GC",
                "SPRING_PROFILES_ACTIVE": props.active_profile,
                "WEATHER_API_SECRET_NAME": props.weather_secret_name,
                "ZIPKIN_HOST": props.zipkin_info["zipkin-host"],
                "ZIPKIN_PORT": props.zipkin_info["zipkin-port"],
                "QDRANT_HOST": props.qdrant_info["qdrant-host"],
                "QDRANT_PORT": props.qdrant_info["qdrant-port"]
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix=f"{pipeline_env}-mcp", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8075, name=f"{pipeline_env}-mcp-http", protocol=ecs.Protocol.TCP)],
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8075/actuator/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60)
            )

        )
        self.mcp_service = ecs.FargateService(self, f"{pipeline_env}-McpService",
            cluster=props.cluster,
            task_definition=self.mcp_task_def,
            desired_count=2,
            assign_public_ip=False,
            service_name=f"{pipeline_env}-mcp-service",
            enable_execute_command=True
        )
        self.mcp_service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix=f"{pipeline_env}-mcp-connect", 
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name=f"{pipeline_env}-mcp-http", 
                    dns_name="mcp-svc",
                    port=8075,
                    discovery_name="mcp-svc",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )
