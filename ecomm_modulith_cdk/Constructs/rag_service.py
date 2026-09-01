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
class RagProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    task_role: iam.Role
    execution_role: iam.Role
    repo_secret: secretsmanager.ISecret
    namespace: str
    active_profile: str
    qdrant_info: dict
    model_info: dict
    zipkin_info: dict
    environment: str

class RagService(Construct):
    def __init__(self, scope: Construct, id: str, props: RagProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)

        rag_image = "ghcr.io/derrick4084/spring-ai-rag:latest"
        pipeline_env = props.environment

        # Create Fargate Task Definition and Service
        self.rag_task_def = ecs.FargateTaskDefinition(self, f"{pipeline_env}-RagServiceTaskDef", 
                    execution_role=props.execution_role,
                    task_role=props.task_role,
                    cpu=1024,
                    memory_limit_mib=2048
                )
        self.rag_task_def.add_container(id=f"{pipeline_env}-rag",
            image=ecs.ContainerImage.from_registry(rag_image, credentials=props.repo_secret),
            container_name=f"{pipeline_env}-rag",
            environment={
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx1536m -XX:+UseG1GC",
                "SPRING_PROFILES_ACTIVE": props.active_profile,
                "MODEL_IP": props.model_info["model-ip"] if props.model_info else "localhost",
                "MODEL_DNS": props.model_info["model-dns"] if props.model_info else "localhost",
                "ZIPKIN_HOST": props.zipkin_info["zipkin-host"],
                "ZIPKIN_PORT": props.zipkin_info["zipkin-port"],
                "QDRANT_HOST": props.qdrant_info["qdrant-host"],
                "QDRANT_PORT": props.qdrant_info["qdrant-port"]
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix=f"{pipeline_env}-rag", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8080, name=f"{pipeline_env}-rag-http", protocol=ecs.Protocol.TCP)]
        )
        self.rag_service = ecs_patterns.ApplicationLoadBalancedFargateService(self, f"{pipeline_env}-RagService",
            cluster=props.cluster,
            desired_count=2,
            public_load_balancer=True,
            service_name=f"{pipeline_env}-rag-service",
            load_balancer_name=f"{pipeline_env}-spring-lb-service",
            protocol=elbv2.ApplicationProtocol.HTTP,
            task_definition=self.rag_task_def,
            health_check_grace_period=Duration.seconds(60)
        )
        self.rag_service.target_group.configure_health_check(
            path="/actuator/health",
            port="8080",
            interval=Duration.seconds(45),
            timeout=Duration.seconds(10),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )
        self.rag_service.service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix=f"{pipeline_env}-rag-connect",
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name=f"{pipeline_env}-rag-http", 
                    dns_name="rag-svc",
                    port=8080,
                    discovery_name="rag-svc",
                    idle_timeout=Duration.hours(1)
                )
            ]
        )

    @property
    def dns_name(self) -> str:
        return self.rag_service.load_balancer.load_balancer_dns_name

    @property
    def service_name(self) -> str:
        return self.rag_service.service.service_name



