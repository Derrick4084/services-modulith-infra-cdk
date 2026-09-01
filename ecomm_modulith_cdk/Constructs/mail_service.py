from aws_cdk import (
    Duration,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager
)
from constructs import Construct
from dataclasses import dataclass



@dataclass
class MailProps:
    """Optional: Define a class or typed dict to handle input configurations cleanly."""
    cluster: ecs.Cluster
    execution_role: iam.Role
    namespace: str

class MailService(Construct):
    def __init__(self, scope: Construct, id: str, props: MailProps, **kwargs) -> None:
        super().__init__(scope, id,**kwargs)


        self.mail_service_task_def = ecs.FargateTaskDefinition(self, "MailServiceTaskDef",
            cpu=1024,
            memory_limit_mib=2048,
            execution_role=props.execution_role
        )
        self.mail_service_task_def.add_container("smtp-mail-svc",
            image=ecs.ContainerImage.from_registry("maildev/maildev"),
            container_name="smtp-mail-svc",
            environment={
                "MAILDEV_SMTP_PORT": "1025",
                "MAILDEV_WEB_PORT": "1080",
                "MAILDEV_INCOMING_USER": "mailuser",
                "MAILDEV_INCOMING_PASS": "mailpassword",
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="smtp-mail-svc", log_retention=logs.RetentionDays.ONE_DAY),
            port_mappings=[
                ecs.PortMapping(container_port=1080, name="http", protocol=ecs.Protocol.TCP),
                ecs.PortMapping(container_port=1025, name="smtp", protocol=ecs.Protocol.TCP)
            ]
        )
        self.mail_service = ecs_patterns.ApplicationLoadBalancedFargateService(self, "MailService",
            cluster=props.cluster, 
            desired_count=1,
            public_load_balancer=True,
            service_name="smtp-mail-svc",
            load_balancer_name="micro-mail-svc-lb",
            protocol=elbv2.ApplicationProtocol.HTTP,
            task_definition=self.mail_service_task_def,
            health_check_grace_period=Duration.seconds(60),
            enable_execute_command=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True)

        )
        self.mail_service.target_group.configure_health_check(
            path="/",
            port="1080",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )
        self.mail_service.service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(
                stream_prefix="mail-svc-connect", 
                log_retention=logs.RetentionDays.ONE_DAY
            ),
            namespace=props.namespace,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name="smtp", 
                    dns_name="smtp-mail-svc",
                    port=1025,
                    discovery_name="smtp-mail-svc",
                    idle_timeout=Duration.hours(1)
                    )]
            )
        self.mail_service.service.connections.security_groups[0].add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(1025),
            description="Allow incoming traffic to MailDev mail interface"
        )