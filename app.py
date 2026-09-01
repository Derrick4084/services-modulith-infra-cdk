#!/usr/bin/env python3
import os
import aws_cdk as cdk


from ecomm_modulith_cdk.Vpc.vpc_stack import VpcStack
from ecomm_modulith_cdk.Fargate.fargate_stack import EcsFargateStack
from ecomm_modulith_cdk.DocumentDb.documentdb_stack import DocumentDBStack
from ecomm_modulith_cdk.Postgres.postgresdb_stack import PostgresDBStack
from ecomm_modulith_cdk.Postgres.postgres_config_stack import PostgresConfigStack
from ecomm_modulith_cdk.Model.ai_model_stack import AiModelStack
from ecomm_modulith_cdk.Redis.redis_stack import RedisClusterStack
from ecomm_modulith_cdk.Redis.redis_insight_stack import RedisInsightStack
from ecomm_modulith_cdk.Qdrant.qdrant_stack import QdrantStack
from ecomm_modulith_cdk.Zipkin.zipkin_stack import ZipkinStack


app = cdk.App()

pipeline_profile = os.getenv("ENVIRONMENT", "prod")

# Create the VPC for the entire application, all other stacks depend on this
default_vpc = VpcStack(app, f"{pipeline_profile}-VpcStack",
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)

ai_model_stack = AiModelStack(app, f"{pipeline_profile}-AiModelStack",
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
ai_model_stack.add_dependency(default_vpc)


qdrant_stack = QdrantStack(app, f"{pipeline_profile}-QdrantStack",
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID,
        region=cdk.Aws.REGION
    )
)
qdrant_stack.add_dependency(default_vpc)


zipkin_stack = ZipkinStack(app, f"{pipeline_profile}-ZipkinStack",
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID,
        region=cdk.Aws.REGION
    )
)
zipkin_stack.add_dependency(default_vpc)


redis_cluster_stack = RedisClusterStack(app, f"{pipeline_profile}-RedisClusterStack",
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID,
        region=cdk.Aws.REGION
    )
)
redis_cluster_stack.add_dependency(default_vpc)


if pipeline_profile == "dev":

    redis_insight_stack = RedisInsightStack(app, f"{pipeline_profile}-RedisInsightStack",
        vpc=default_vpc.get_vpc,
        environment = pipeline_profile,
        redis_info=redis_cluster_stack.redis_info,
        env=cdk.Environment(
            account=cdk.Aws.ACCOUNT_ID,
            region=cdk.Aws.REGION
        )
    )
    redis_insight_stack.add_dependency(redis_cluster_stack)



# Creates the document dbs Customers and Notifications, depends on the VPC
documentdb_stack = DocumentDBStack(app, f"{pipeline_profile}-DocumentDBStack", 
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    ),
)
documentdb_stack.add_dependency(default_vpc)

# Creates Posgres db for Orders, Payments, Products,
# Shipments and Users service, depends on the VPC
postgresdb_stack = PostgresDBStack(app, f"{pipeline_profile}-PostgresDBStack", 
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
postgresdb_stack.add_dependency(default_vpc)


# Creates databases and tables in postgres depends on Postgres 
postgres_config_stack = PostgresConfigStack(app, f"{pipeline_profile}-PostgresConfigStack",
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    pg_info=postgresdb_stack.postgres_info,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
postgres_config_stack.add_dependency(postgresdb_stack)


# Creates all the services on ECS Fargate
# depends on all the stacks so deployed last
ecs_fargate = EcsFargateStack(app, f"{pipeline_profile}-EcsFargateStack", 
    vpc=default_vpc.get_vpc,
    environment = pipeline_profile,
    docdb_info=documentdb_stack.docdb_info,
    pg_info=postgresdb_stack.postgres_info,
    redis_info=redis_cluster_stack.redis_info,
    model_info=ai_model_stack.model_info,
    qdrant_info=qdrant_stack.qdrant_info,
    zipkin_info=zipkin_stack.zipkin_info,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
ecs_fargate.add_dependency(default_vpc)
ecs_fargate.add_dependency(redis_cluster_stack)
ecs_fargate.add_dependency(documentdb_stack)
ecs_fargate.add_dependency(postgresdb_stack)
ecs_fargate.add_dependency(ai_model_stack)
ecs_fargate.add_dependency(qdrant_stack)


app.synth()
