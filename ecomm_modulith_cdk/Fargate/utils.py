from aws_cdk import Duration, Aws
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_servicediscovery as service_discovery
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from constructs import Construct

GRPC_SERVICES = ["grpc-order-svc", "grpc-product-svc", "grpc-customer-svc", "grpc-payment-svc", "grpc-shipping-svc"]

    
def create_internal_service(
        scope,
        cluster: ecs.Cluster, 
        name: str, 
        image: str, 
        namespace: service_discovery.PrivateDnsNamespace,
        kafka_info: dict = None,
        execution_role: iam.Role = None,
        task_role: iam.Role = None,
        repo_secret: secretsmanager.Secret = None,
        docdb_info: dict = None,
        postgres_info: dict = None,
        start_period_seconds: int = 150,
        health_check_grace_period_seconds: int = 240,
        cpu_limit: int = 512,
        memory_limit: int = 2048,
        jvm_opt: str = "-Xms512m -Xmx1280m -XX:+UseG1GC"
    ) -> ecs.FargateService:
            
            cpu = cpu_limit
            memory_limit_mib = memory_limit
            jvm_options = jvm_opt

            task_definition = ecs.FargateTaskDefinition(scope, f"{name}TaskDef",
                execution_role=execution_role,
                task_role=task_role,
                cpu=cpu,
                memory_limit_mib=memory_limit_mib
            )

            container_config = {
                "image": ecs.ContainerImage.from_registry(image, credentials=repo_secret),
                "container_name": name,
                "cpu": cpu,
                "memory_limit_mib": memory_limit_mib,
                "logging": ecs.LogDrivers.aws_logs(
                     stream_prefix=f"{name}Logs",
                     log_retention=logs.RetentionDays.ONE_WEEK
                    )
            }

            environment_dict = {}
            
            environment_dict["GRPC_PORT"] = "9090"
            environment_dict["PAYMENT_SERVICE_ADDR"] = "grpc-payment-svc"
            environment_dict["PRODUCT_SERVICE_ADDR"] = "grpc-product-svc"
            environment_dict["CUSTOMER_SERVICE_ADDR"] = "grpc-customer-svc"
            environment_dict["ORDER_SERVICE_ADDR"] = "grpc-order-svc"
            environment_dict["SHIPPING_SERVICE_ADDR"] = "grpc-shipping-svc"
            environment_dict["JAVA_TOOL_OPTIONS"] = jvm_options

            if docdb_info:
                environment_dict["DOCUMENT_DB_SECRET_NAME"] = docdb_info["secret-name"]
            if kafka_info:
                environment_dict["SPRING_KAFKA_BOOTSTRAP_SERVERS"] = kafka_info["bootstrap_brokers_tls"]     
            if postgres_info:
                environment_dict["POSTGRES_DB_SECRET_NAME"] = postgres_info["secret-name"]
                                     
            
            container_config["environment"] = environment_dict

            is_grpc = name in GRPC_SERVICES

            if is_grpc:
                task_definition.add_container(
                    f"{name}Container",
                    port_mappings=[ecs.PortMapping(container_port=9090, name="grpc", protocol=ecs.Protocol.TCP)],
                    health_check=ecs.HealthCheck(
                        command=["CMD-SHELL", "grpc_health_probe -addr=:9090 || exit 1"],
                        interval=Duration.seconds(45),
                        timeout=Duration.seconds(10),
                        retries=5,
                        start_period=Duration.seconds(start_period_seconds),
                    ),
                **container_config
            )
            else:
                task_definition.add_container(
                f"{name}Container",
                port_mappings=[ecs.PortMapping(container_port=8080, name="http", protocol=ecs.Protocol.TCP)],
                health_check=ecs.HealthCheck(
                    # command=["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:8080/actuator/health || exit 1"],
                    command=["CMD-SHELL", "nc -z localhost 8080 || exit 1"],
                    interval=Duration.seconds(45),
                    timeout=Duration.seconds(10),
                    retries=5,
                    start_period=Duration.seconds(start_period_seconds),
                ),
                **container_config
            )

            service = ecs.FargateService(scope, f"{name}Service",
                cluster=cluster,
                task_definition=task_definition,
                desired_count=2,
                assign_public_ip=False,
                service_name=name,
                availability_zone_rebalancing=ecs.AvailabilityZoneRebalancing.ENABLED,
                service_connect_configuration=ecs.ServiceConnectProps(
                    namespace=namespace.namespace_arn,
                    log_driver=ecs.LogDriver.aws_logs(stream_prefix=f"{name}-svc-connect", log_retention=logs.RetentionDays.ONE_DAY),
                    services=[
                        ecs.ServiceConnectService(
                            port_mapping_name="grpc" if is_grpc else "http",
                            dns_name=name,
                            port=9090 if is_grpc else 8080,
                            discovery_name=name,
                            idle_timeout=Duration.hours(1)
                        ) 
                        
                    ]
                ),
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                enable_execute_command=True,
                health_check_grace_period=Duration.seconds(health_check_grace_period_seconds),
                circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            )
            service.connections.allow_from(      
                ec2.Peer.ipv4(cluster.vpc.vpc_cidr_block),
                ec2.Port.tcp(9090 if is_grpc else 8080),
                f"Allow {name} traffic from VPC"
            )
            return service


def add_cpu_scale_to_zero(service: ecs.FargateService):

    scalable_target = service.auto_scale_task_count(
        min_capacity=0,
        max_capacity=10
    )

    # Scale OUT when CPU > 50%
    scalable_target.scale_on_cpu_utilization(
        f"{service.service_name}CpuScaleOut",
        target_utilization_percent=50,
        scale_in_cooldown=Duration.minutes(5),
        scale_out_cooldown=Duration.minutes(1),
    )

    # Scale IN to zero when CPU ~ 0
    zero_cpu_metric = cloudwatch.Metric(
        namespace="AWS/ECS",
        metric_name="CPUUtilization",
        dimensions_map={
            "ClusterName": service.cluster.cluster_name,
            "ServiceName": service.service_name,
        },
        statistic="Average",
        period=Duration.minutes(5),
    )

    scalable_target.scale_on_metric(
        f"{service.service_name}ScaleToZero",
        metric=zero_cpu_metric,
        scaling_steps=[
            appscaling.ScalingInterval(upper=1, change=-10),  # effectively go to 0
        ],
        cooldown=Duration.minutes(10),
        adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
    )
    

def add_autoscaling(service: ecs.FargateService):
    scalable_target = service.auto_scale_task_count(
        min_capacity=2,
        max_capacity=10
    )
    scalable_target.scale_on_cpu_utilization(
        "CpuScaling",
        target_utilization_percent=70,
        scale_in_cooldown=Duration.seconds(60),
        scale_out_cooldown=Duration.seconds(60)
    )
   

def add_kafka_lag_scaling(service: ecs.FargateService):
    lag_metric = cloudwatch.Metric(
        namespace="Custom/Kafka",
        metric_name="ConsumerLag",
        dimensions_map={
            "Service": service.service_name
        },
        statistic="Average",
        period=Duration.minutes(1)
    )

    scalable_target = service.auto_scale_task_count(
        min_capacity=2,
        max_capacity=10
    )

    scalable_target.scale_on_metric(
        "KafkaLagScaling",
        metric=lag_metric,
        scaling_steps=[
            appscaling.ScalingInterval(upper=100, change=-1),
            appscaling.ScalingInterval(lower=500, change=+1),
            appscaling.ScalingInterval(lower=1000, change=+2)
        ],
        adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        cooldown=Duration.minutes(2)
    )


def add_kafka_scale_to_zero(service: ecs.FargateService):
    scalable_target = service.auto_scale_task_count(
        min_capacity=0,
        max_capacity=10  # ⚠️ set <= number of partitions
    )

    lag_metric = cloudwatch.Metric(
        namespace="Custom/Kafka",
        metric_name="ConsumerLag",
        dimensions_map={
            "Service": service.service_name
        },
        statistic="Average",
        period=Duration.minutes(1)
    )

    scalable_target.scale_on_metric(
        "KafkaLagScaling",
        metric=lag_metric,
        scaling_steps=[
            appscaling.ScalingInterval(upper=0, change=-10),     # no lag → go to 0
            appscaling.ScalingInterval(lower=1, change=+1),     # some lag → scale out
            appscaling.ScalingInterval(lower=1000, change=+3),  # big lag → scale faster
        ],
        adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        cooldown=Duration.minutes(2)
    )


    

    
        
    
        


