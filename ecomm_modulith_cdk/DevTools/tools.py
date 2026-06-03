from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_secretsmanager as secretsmanager,
    aws_logs as logs

)
from constructs import Construct


def _add_cert_init(task_def: ecs.FargateTaskDefinition, s3_uri: str, log_prefix: str):
    task_def.add_volume(name="certs")
    init = task_def.add_container(f"{log_prefix}-cert-init",
        image=ecs.ContainerImage.from_registry("amazon/aws-cli:latest"),
        container_name=f"{log_prefix}-cert-init",
        essential=False,
        command=["s3", "cp", s3_uri, "/certs/ca-bundle.pem"],
        logging=ecs.LogDriver.aws_logs(stream_prefix=f"{log_prefix}-cert-init", log_retention=logs.RetentionDays.ONE_DAY),
    )
    init.add_mount_points(ecs.MountPoint(container_path="/certs", source_volume="certs", read_only=False))
    return init


class DevToolStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.IVpc, ecs_info: dict, docdb_info: dict,
                ca_bundle_s3_uri: str = None, **kwargs) -> None:
        super().__init__(scope, construct_id, description="Mongo Express service for DocumentDB. USE FOR DEVELOPEMENT ONLY", **kwargs)
      
        cluster = ecs.Cluster.from_cluster_attributes(self, "ECSCluster",
            cluster_name=ecs_info["cluster-name"],
            cluster_arn=ecs_info["cluster-arn"],
            vpc=vpc
        )
        task_role = iam.Role.from_role_arn(self, "MongoExpressTaskRole", role_arn=ecs_info["task-role-arn"])
        execution_role = iam.Role.from_role_arn(self, "MongoExpressExecutionRole", role_arn=ecs_info["execution-role-arn"])
        
        mongo_secret = secretsmanager.Secret.from_secret_name_v2(
            scope=self,
            id="MongoExpressSecret",
            secret_name=docdb_info["secret-name"]
        )
        documentdb_endpoint = mongo_secret.secret_value_from_json("documentdb_endpoint").unsafe_unwrap()
        port = mongo_secret.secret_value_from_json("port").unsafe_unwrap()
        username = mongo_secret.secret_value_from_json("username").unsafe_unwrap()
        password = mongo_secret.secret_value_from_json("password").unsafe_unwrap()
        documentdb_uri = f"mongodb://{username}:{password}@{documentdb_endpoint}:{port}/?ssl=true&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false"
        
          
        # Create the mongo express service for documentdb cluster
        mongo_express_task_def = ecs.FargateTaskDefinition(self, "MongoExpressTaskDef",
            memory_limit_mib=1024,
            cpu=512,
            execution_role=execution_role,
            task_role=task_role
        )
        cert_init = _add_cert_init(mongo_express_task_def, ca_bundle_s3_uri, "documentdb") if ca_bundle_s3_uri else None
        main_container = mongo_express_task_def.add_container("mongo-express",
            image=ecs.ContainerImage.from_registry("mongo-express:latest"),
            container_name="mongo-express",
            environment={
                "ME_CONFIG_MONGODB_URL": documentdb_uri,       
                "ME_CONFIG_MONGODB_SSL": "true",
                "ME_CONFIG_BASICAUTH_USERNAME": "admin",
                "ME_CONFIG_BASICAUTH_PASSWORD": "password123",
                "ME_CONFIG_MONGODB_AUTH_DATABASE": "admin",
                "ME_CONFIG_MONGODB_AUTH_SOURCE": "admin",
                "ME_CONFIG_MONGODB_CA_FILE": "/certs/ca-bundle.pem",
                "ME_CONFIG_HEALTH_CHECK_PATH": "/status"
            },
            logging=ecs.LogDriver.aws_logs(stream_prefix="mongo-express", log_retention=logs.RetentionDays.ONE_DAY),
            port_mappings=[
                ecs.PortMapping(container_port=8081, name="http", protocol=ecs.Protocol.TCP)
            ]
        )


        if cert_init:
            main_container.add_mount_points(ecs.MountPoint(container_path="/certs", source_volume="certs", read_only=True))
            main_container.add_container_dependencies(ecs.ContainerDependency(
                container=cert_init,
                condition=ecs.ContainerDependencyCondition.SUCCESS
            ))       
        mongo_express_for_documentdb = ecs_patterns.ApplicationLoadBalancedFargateService(self, "MongoExpressService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            public_load_balancer=True,
            load_balancer_name="mongo-exp-documentdb-lb",
            service_name="mongo-express-documentdb-svc",
            protocol=elbv2.ApplicationProtocol.HTTP,
            task_definition=mongo_express_task_def,
            health_check_grace_period=Duration.seconds(60),
            enable_execute_command=True,
        )
        mongo_express_for_documentdb.target_group.configure_health_check(
            path="/status",
            port="8081",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(5),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )

        CfnOutput(self, "MongoExpressDocumentDBALB", 
                value=mongo_express_for_documentdb.load_balancer.load_balancer_dns_name,
                export_name="MongoExpressDocumentDBALB"
    )


        