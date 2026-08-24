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
    namespace: str
    zipkin_host: str
    active_profile: str


class McpService(Construct):
    def __init__(self, scope: Construct, id: str, props: McpProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)


        mcp_image = "ghcr.io/derrick4084/spring-ai-mcp:latest"


        self.mcp_task_def = ecs.FargateTaskDefinition(self, "McpServiceTaskDef",
                    execution_role=props.execution_role,
                    task_role=props.task_role,
                    cpu=1024,
                    memory_limit_mib=2048
                )
        self.mcp_task_def.add_container("spring-ai-mcp",
            image=ecs.ContainerImage.from_registry(mcp_image, credentials=props.repo_secret),
            container_name="spring-ai-mcp",
            environment={
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx1536m -XX:+UseG1GC",
                "SPRING_PROFILES_ACTIVE": props.active_profile,
                "WEATHER_API_SECRET_NAME": "open-weather-api",
                "ZIPKIN_HOST": props.zipkin_host 
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="spring-ai-mcp", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8075, name="mcp-http", protocol=ecs.Protocol.TCP)],
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8075/actuator/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60)
            )


        )
        self.mcp_service = ecs.FargateService(self, "McpService",
            cluster=props.cluster,
            task_definition=self.mcp_task_def,
            desired_count=2,
            assign_public_ip=False,
            service_name="ecomm-ai-mcp",
            enable_execute_command=True
        )
        self.mcp_service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix="ecomm-ai-mcp-connect", 
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name="mcp-http", 
                    dns_name="ecomm-ai-mcp",
                    port=8075,
                    discovery_name="ecomm-ai-mcp",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )
