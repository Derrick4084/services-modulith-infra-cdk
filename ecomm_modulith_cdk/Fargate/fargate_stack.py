from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    Aws,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_secretsmanager as secretsmanager,
    aws_logs as logs
)
from constructs import Construct



class EcsFargateStack(Stack):
    def __init__(self, scope: Construct, 
                 construct_id: str, 
                 vpc: ec2.Vpc, 
                 pg_info: dict,
                 docdb_info: dict,
                 ca_bundle_s3_uri: str = None,
                 run_mail_service: bool = True,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, description="ECS Fargate cluster for Ecomm Application", **kwargs)


        self.vpc = vpc
        self.docdb_info = docdb_info
        self.pg_info = pg_info
   

        app_image = "ghcr.io/derrick4084/services-modulith:latest"

        # Create an ECS Cluster within the provided VPC
        # and default namespace for the cluster
        self.cluster = ecs.Cluster(self, "EcsCluster",
            vpc=self.vpc,
            cluster_name="microservices",
            enable_fargate_capacity_providers=True
        )
        namespace = self.cluster.add_default_cloud_map_namespace(
            name="services.local",
            use_for_service_connect=True
           )
           
        # Create IAM roles for the ECS tasks
        # Execution role for the ECS tasks
        self.execution_role = iam.Role(self, "ExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ],
            role_name="MicroservicesEcsExecutionRole",
            inline_policies={
                "SecretsManagerAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "secretsmanager:GetSecretValue", 
                                "secretsmanager:DescribeSecret"
                            ],
                            resources=[f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:*"]
                        )
                    ]
                ),
                "S3Access": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "s3:GetObject"  
                            ],
                            resources=["arn:aws:s3:::all-purpose-utility/certs/ca-bundle.pem"]
                        )
                    ]
                )
            }
        )
        
       # Task role for the ECS tasks
        self.task_role = iam.Role(self, "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name="MicroservicesEcsTaskRole",       
        )
        self.task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "s3:GetObject"
            ],
            resources=[f"arn:aws:s3:::all-purpose-utility/certs/ca-bundle.pem"]
        ))
        
        # Add permissions to the task role to allow it to access the database
        self.task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "rds-db:DescribeDBClusters",
                "rds-db:Connect",
                "rds-db:DescribeDBInstances",
                "rds-db:DeleteDBInstance",
                "rds-db:CreateDBInstance",
                "rds-db:ModifyDBInstance"
            ],
            resources=["*"] 
        ))
        # Add permissions to the task role to allow it to access secrets manager
        self.task_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue",
                     "secretsmanager:DescribeSecret"],
            resources=[f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:*"]
        ))
        # Add permissions to the task role to allow it to access the DocumentDB cluster
        self.task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "documentdb:Connect",
                "documentdb:DescribeDBClusters",
                "documentdb:Read",
                "documentdb:Write"
            ],
            resources=["*"]
        ))
        if ca_bundle_s3_uri:
            bucket_name = ca_bundle_s3_uri.replace("s3://", "").split("/")[0]
            key = "/".join(ca_bundle_s3_uri.replace("s3://", "").split("/")[1:])
            self.task_role.add_to_policy(iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"arn:aws:s3:::{bucket_name}/{key}"]
        ))
            
        
        container_registry_secret = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="GithubTokenByName",
            secret_name="github-secret-token"
        )


        """
        Create the Ecomm application service running on Fargate with an Application Load Balancer to expose the service to the internet.
         - The service will run 2 tasks for high availability and load balancing.
         - The service will be registered with Cloud Map for service discovery.
         - The service will have a health check configured to monitor the health of the application.
         - The service will have a circuit breaker enabled to automatically roll back failed deployments.
         - The service will have a grace period for health checks to allow the application to start up before health checks are performed.
         - The service will have execute command enabled for debugging purposes.
         - The service will have environment variables configured to pass database connection information and JVM options to the
        """ 
        fargate_task_def = ecs.FargateTaskDefinition(self, "FargateServiceTaskDef",
            execution_role=self.execution_role,
            task_role=self.task_role,
            cpu=512,
            memory_limit_mib=1024
        )
        fargate_task_def.add_container("ecomm-app-svc",
            image=ecs.ContainerImage.from_registry(app_image, credentials=container_registry_secret),
            container_name="ecomm-app-service",
            environment={    
                "POSTGRES_DB_SECRET_NAME": pg_info["secret-name"],
                "DOCUMENTDB_SECRET_NAME": docdb_info["secret-name"],
                "JAVA_TOOL_OPTIONS": "-Xms512m -Xmx3200m -XX:+UseG1GC",
                "SPRING_PROFILES_ACTIVE": "prod"
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="ecomm-app-service", log_retention=logs.RetentionDays.ONE_WEEK),
            port_mappings=[ecs.PortMapping(container_port=8080, name="app-http", protocol=ecs.Protocol.TCP)]
        )
        self.fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(self, "EcommAppService",
            cluster=self.cluster,
            cpu=1024,
            memory_limit_mib=4096,
            desired_count=2,
            public_load_balancer=True,
            service_name="ecomm-app-svc",
            load_balancer_name="ecomm-app-svc-lb",
            protocol=elbv2.ApplicationProtocol.HTTP,
            task_definition=fargate_task_def,
            health_check_grace_period=Duration.seconds(60),
            enable_execute_command=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True)      
        )
        # # Set up health check for the rest service
        self.fargate_service.target_group.configure_health_check(
            path="/actuator/health",
            port="8080",
            interval=Duration.seconds(45),
            timeout=Duration.seconds(10),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )
        self.fargate_service.service.enable_service_connect(
            log_driver=ecs.LogDriver.aws_logs(stream_prefix="ecomm-app-svc-connect", log_retention=logs.RetentionDays.ONE_DAY),
            namespace=namespace.namespace_name,
            services=[
                ecs.ServiceConnectService(
                    port_mapping_name="app-http", 
                    dns_name="ecomm-app-svc",
                    port=8080,
                    discovery_name="ecomm-app-svc",
                    idle_timeout=Duration.hours(1)
                    )]
        )


        """
        Create the mail service with load balancer to expose UI
        TODO: Can be removed in production. Change destination in application.
        """

        if run_mail_service:

            mail_service_task_def = ecs.FargateTaskDefinition(self, "MailServiceTaskDef",
                memory_limit_mib=1024,
                cpu=512,
                execution_role=self.execution_role,
                task_role=self.task_role
            )
            mail_service_task_def.add_container("smtp-mail-svc",
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
            mail_service = ecs_patterns.ApplicationLoadBalancedFargateService(self, "MailService",
                cluster=self.cluster,
                cpu=512,
                memory_limit_mib=1024,
                desired_count=1,
                public_load_balancer=True,
                service_name="smtp-mail-svc",
                load_balancer_name="micro-mail-svc-lb",
                protocol=elbv2.ApplicationProtocol.HTTP,
                task_definition=mail_service_task_def,
                health_check_grace_period=Duration.seconds(60),
                enable_execute_command=True,
                circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True)

            )
            mail_service.target_group.configure_health_check(
                path="/",
                port="1080",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3
            )
            mail_service.service.enable_service_connect(
                log_driver=ecs.LogDriver.aws_logs(
                    stream_prefix="mail-svc-connect", 
                    log_retention=logs.RetentionDays.ONE_DAY
                ),
                namespace=namespace.namespace_name,
                services=[
                    ecs.ServiceConnectService(
                        port_mapping_name="smtp", 
                        dns_name="smtp-mail-svc",
                        port=1025,
                        discovery_name="smtp-mail-svc",
                        idle_timeout=Duration.hours(1)
                        )]
                )
            mail_service.service.connections.security_groups[0].add_ingress_rule(
                peer=ec2.Peer.any_ipv4(),
                connection=ec2.Port.tcp(1025),
                description="Allow incoming traffic to MailDev mail interface"
            )
        
   
               
        # Create security group rules for the services that need DocumentDb
        docdb_sg = ec2.SecurityGroup.from_security_group_id(self, "DocDbSG", self.docdb_info["documentdb_sg_id"])
        docdb_sg.add_ingress_rule(
            peer=self.fargate_service.service.connections.security_groups[0],
            connection=ec2.Port.tcp(27017),
            description="Allow Ecomm App service to access DocumentDB"
        )

           
        # Create security group rules for the services that need to access Postgres
        postgres_sg = ec2.SecurityGroup.from_security_group_id(self, "PostgresSG", self.pg_info["security-group-id"])
       
        postgres_sg.add_ingress_rule(
            peer=self.fargate_service.service.connections.security_groups[0],
            connection=ec2.Port.tcp(5432),
            description="Allow ECS to talk to Postgres"
        )
             
        
        CfnOutput(self, "EcommAppServiceALB", value=self.fargate_service.load_balancer.load_balancer_dns_name,
            export_name="EcommAppServiceALB"
        )

    @property
    def ecs_info(self) -> dict:
        return {
            "cluster-name": self.cluster.cluster_name,
            "cluster-arn": self.cluster.cluster_arn,
            "service-name": self.fargate_service.service.service_name,
            "task-role-arn": self.task_role.role_arn,
            "execution-role-arn": self.execution_role.role_arn,
            "documentdb-sg-id": self.docdb_info["documentdb_sg_id"]
        }



