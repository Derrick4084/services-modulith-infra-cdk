from aws_cdk import (
    Stack,
    CfnOutput,
    Aws,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager
    
)
from constructs import Construct

from ecomm_modulith_cdk.Constructs.ecomm_service import EcommService, EcommProps
from ecomm_modulith_cdk.Constructs.rag_service import RagService, RagProps
from ecomm_modulith_cdk.Constructs.mcp_service import McpService, McpProps
from ecomm_modulith_cdk.Constructs.mail_service import MailService, MailProps
from ecomm_modulith_cdk.Constructs.mongo_exp_service import MongoExpressProps, MongoExpressService


class EcsFargateStack(Stack):
    def __init__(self, scope: Construct, 
                 construct_id: str, 
                 vpc: ec2.Vpc, 
                 pg_info: dict,
                 docdb_info: dict,
                 model_info: dict,
                 redis_info: dict,
                 qdrant_info: dict,
                 zipkin_info: dict,
                 environment: str,
                 run_mail_service: bool = True,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, description="ECS Fargate cluster for Ecomm Application", **kwargs)


        self.vpc = vpc
        self.docdb_info = docdb_info
        self.pg_info = pg_info
        self.model_info = model_info
        self.qdrant_info = qdrant_info
        self.redis_info = redis_info
        self.zipkin_info = zipkin_info

        spring_active_profile = "prod"
        pipeline_env = environment



        # shared_efs_fs = efs.FileSystem(
        #     self, "ZipkinEFS",
        #     vpc=self.vpc,
        #     removal_policy=RemovalPolicy.DESTROY,
        #     lifecycle_policy=efs.LifecyclePolicy.AFTER_7_DAYS,  # files are moved to EFS Infrequent Access after 7 days
        #     performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
        #     throughput_mode=efs.ThroughputMode.BURSTING
        # )    


        # ebs_data_volume = ecs.ServiceManagedVolume(
        #     scope=self,
        #     id="RedisDataVolume",
        #     name="redis-data",
        #     managed_ebs_volume=ecs.ServiceManagedEBSVolumeConfiguration(
        #         size=Size.gibibytes(20),  # Size in GiB
        #         iops=3000,  # IOPS for the volume  # Throughput in MiB/s
        #         throughput=125,  # Throughput in MiB/s
        #         volume_type=ec2.EbsDeviceVolumeType.GP3,  # Volume type
        #         encrypted=True 
        #     )
        # )
        
        # Create an ECS Cluster within the provided VPC
        # and default namespace for the cluster
        self.cluster = ecs.Cluster(self, f"{pipeline_env}-EcsCluster",
            vpc=self.vpc,
            cluster_name=f"{pipeline_env}-microservices",
            enable_fargate_capacity_providers=True
        )
        namespace = self.cluster.add_default_cloud_map_namespace(
            name=f"{pipeline_env}.local",
            use_for_service_connect=True
           )
           
        # Create IAM roles for the ECS tasks
        # Execution role for the ECS tasks
        self.execution_role = iam.Role(self, f"{pipeline_env}-ExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ],
            role_name=f"{pipeline_env}-MicroservicesEcsExecutionRole",
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
        self.task_role = iam.Role(self, f"{pipeline_env}-TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name=f"{pipeline_env}-MicroservicesEcsTaskRole",       
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
        # if ca_bundle_s3_uri:
        #     bucket_name = ca_bundle_s3_uri.replace("s3://", "").split("/")[0]
        #     key = "/".join(ca_bundle_s3_uri.replace("s3://", "").split("/")[1:])
        #     self.task_role.add_to_policy(iam.PolicyStatement(
        #         actions=["s3:GetObject"],
        #         resources=[f"arn:aws:s3:::{bucket_name}/{key}"]
        #  )
        # )
                      
        self.container_registry_secret = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id=f"{pipeline_env}-GithubTokenByName",
            secret_name="github-secret-token"
        )


        self.weather_api = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id=f"{pipeline_env}-OpenWeatherTokenByName",
            secret_name="open-weather-api"
        )
        
        self.pg_secret=secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id=f"{pipeline_env}-PostgresSecretByName",
            secret_name=pg_info["secret-name"]
        )

        self.docdb_secret=secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id=f"{pipeline_env}-DocumentDbSecretByName",
            secret_name=docdb_info["secret-name"]
        )
      
        mcp_config = McpProps(  
            cluster=self.cluster,
            task_role=self.task_role,
            execution_role=self.execution_role,
            repo_secret=self.container_registry_secret,
            weather_secret_name=self.weather_api.secret_name,
            namespace=namespace.namespace_name,
            qdrant_info=self.qdrant_info,
            zipkin_info=self.zipkin_info,
            active_profile=spring_active_profile,
            environment=pipeline_env
        )
        self.mcp_service = McpService(self, f"{pipeline_env}-McpService", props=mcp_config)

        rag_config = RagProps(
            cluster=self.cluster,
            task_role=self.task_role,
            execution_role=self.execution_role,
            repo_secret=self.container_registry_secret,
            namespace=namespace.namespace_name,
            qdrant_info=self.qdrant_info,
            zipkin_info=self.zipkin_info,
            active_profile=spring_active_profile,
            model_info=self.model_info,
            environment=pipeline_env
        )
        self.rag_service = RagService(self, f"{pipeline_env}-RagService", props=rag_config)
        self.rag_service.node.add_dependency(self.mcp_service)

        
        if pipeline_env == "dev":

            mongo_express_config = MongoExpressProps(
                cluster=self.cluster,
                execution_role=self.execution_role,
                task_role=self.task_role,
                namespace=namespace.namespace_name,
                secret_name=self.docdb_info["secret-name"]
            )
            self.mongo_express_service = MongoExpressService(self, "MongoExpress", props=mongo_express_config)

        
        
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
            self.mail_service = MailService(self, f"{pipeline_env}-MailService", props=mail_config)
        

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
            redis_info=self.redis_info,
            zipkin_info=self.zipkin_info,
            active_profile=spring_active_profile,
            environment=pipeline_env      
        )
        self.ecomm_service = EcommService(self, f"{pipeline_env}-EcommService", props=ecomm_config)
        self.ecomm_service.node.add_dependency(self.mcp_service)
        self.ecomm_service.node.add_dependency(self.rag_service)

        
        CfnOutput(self, f"{pipeline_env}-RagServiceALB", value=self.rag_service.dns_name,
            export_name=f"{pipeline_env}-RagServiceALB"
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



