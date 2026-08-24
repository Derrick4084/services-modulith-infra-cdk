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

from ecomm_modulith_cdk.Services.ecomm_service import EcommService, EcommProps
from ecomm_modulith_cdk.Services.rag_service import RagService, RagProps
from ecomm_modulith_cdk.Services.mcp_service import McpService, McpProps
from ecomm_modulith_cdk.Services.qdrant_service import QdrantService, QdrantProps
from ecomm_modulith_cdk.Services.mail_service import MailService, MailProps
from ecomm_modulith_cdk.Services.zipkin_service import ZipkinService, ZipkinProps
from ecomm_modulith_cdk.Services.redis_service import RedisService, RedisProps



class EcsFargateStack(Stack):
    def __init__(self, scope: Construct, 
                 construct_id: str, 
                 vpc: ec2.Vpc, 
                 pg_info: dict,
                 docdb_info: dict,
                 model_info: dict = None,
                 ca_bundle_s3_uri: str = None,
                 run_mail_service: bool = True,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, description="ECS Fargate cluster for Ecomm Application", **kwargs)


        self.vpc = vpc
        self.docdb_info = docdb_info
        self.pg_info = pg_info
        self.model_info = model_info

        active_profile = "prod"
        zipkin_host = "zipkin"

        
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
         )
        )
            

               
        self.container_registry_secret = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="GithubTokenByName",
            secret_name="github-secret-token"
        )


        self.weather_api = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="OpenWeatherTokenByName",
            secret_name="open-weather-api"
        )
        

        self.pg_secret=secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="PostgresSecretByName",
            secret_name=pg_info["secret-name"]
        )

        self.docdb_secret=secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="DocumentDbSecretByName",
            secret_name=docdb_info["secret-name"]
        )


        ecomm_config = EcommProps(
            cluster=self.cluster,
            task_role=self.task_role,
            execution_role=self.execution_role,
            repo_secret=self.container_registry_secret,
            pg_secret_name=self.pg_info["secret-name"],
            docdb_secret_name=self.docdb_info["secret-name"],
            docdb_sg_id=self.docdb_info["documentdb_sg_id"],
            pg_sg_id=self.pg_info["security-group-id"],
            namespace=namespace.namespace_name,
            zipkin_host=zipkin_host,
            active_profile=active_profile,
            
        )
        self.ecomm_service = EcommService(self, "EcommService", props=ecomm_config)


        rag_config = RagProps(
            cluster=self.cluster,
            task_role=self.task_role,
            execution_role=self.execution_role,
            repo_secret=self.container_registry_secret,
            namespace=namespace.namespace_name,
            zipkin_host=zipkin_host,
            active_profile=active_profile
        )
        self.rag_service = RagService(self, "RagService", props=rag_config)



        mcp_config = McpProps(  
            cluster=self.cluster,
            task_role=self.task_role,
            execution_role=self.execution_role,
            repo_secret=self.container_registry_secret,
            namespace=namespace.namespace_name,
            zipkin_host=zipkin_host,
            active_profile=active_profile
        )
        self.mcp_service = McpService(self, "McpService", props=mcp_config)



        qdrant_config = QdrantProps(
            cluster=self.cluster,
            execution_role=self.execution_role,
            namespace=namespace.namespace_name
        )
        self.qdrant_service = QdrantService(self, "QdrantService", props=qdrant_config)


        redis_config = RedisProps(
            cluster=self.cluster,
            execution_role=self.execution_role,
            namespace=namespace.namespace_name
        )
        self.redis_service = RedisService(self, "RedisService", props=redis_config)


        zipkin_config = ZipkinProps(
            cluster=self.cluster,
            execution_role=self.execution_role,
            namespace=namespace.namespace_name
        )
        self.zipkin_service = ZipkinService(self, "ZipkinService", props=zipkin_config)



        """
        Create the mail service with load balancer to expose UI
        TODO: Can be removed in production. Change destination in application.
        """

        if run_mail_service:

            mail_config = MailProps(
                        cluster=self.cluster,
                        execution_role=self.execution_role,
                        namespace=namespace.namespace_name
                    )
            self.mail_service = MailService(self, "MailService", props=mail_config)
        
    
        CfnOutput(self, "RagServiceALB", value=self.rag_service.dns_name,
            export_name="RagServiceALB"
        )

    @property
    def ecs_info(self) -> dict:
        return {
            "cluster-name": self.cluster.cluster_name,
            "cluster-arn": self.cluster.cluster_arn,
            "service-name": self.rag_service.service_name,
            "task-role-arn": self.task_role.role_arn,
            "execution-role-arn": self.execution_role.role_arn,
            "documentdb-sg-id": self.docdb_info["documentdb_sg_id"]
        }



