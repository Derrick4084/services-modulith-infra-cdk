#!/usr/bin/env python3
import os
import aws_cdk as cdk


from ecomm_modulith_cdk.Vpc.vpc_stack import VpcStack
from ecomm_modulith_cdk.Fargate.fargate_stack import EcsFargateStack
from ecomm_modulith_cdk.DevTools.tools import DevToolStack
from ecomm_modulith_cdk.DocumentDb.documentdb_stack import DocumentDBStack
from ecomm_modulith_cdk.Postgres.postgresdb_stack import PostgresDBStack
from ecomm_modulith_cdk.Postgres.postgres_config_stack import PostgresConfigStack


app = cdk.App()

# Create the VPC for the entire application, all other stacks depend on this
default_vpc = VpcStack(app, "VpcStack",
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)

# Creates the document dbs Customers and Notifications, depends on the VPC
documentdb_stack = DocumentDBStack(app, "DocumentDBStack", 
    vpc=default_vpc.get_vpc,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    ),
)
documentdb_stack.add_dependency(default_vpc)

# Creates Posgres db for Orders, Payments, Products,
# Shipments and Users service, depends on the VPC
postgresdb_stack = PostgresDBStack(app, "PostgresDBStack", 
    vpc=default_vpc.get_vpc,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
postgresdb_stack.add_dependency(default_vpc)
postgresdb_stack.add_dependency(documentdb_stack)


# Creates databases and tables in postgres depends on Postgres 
postgres_config_stack = PostgresConfigStack(app, "PostgresConfigStack",
    vpc=default_vpc.get_vpc,
    pg_info=postgresdb_stack.postgres_info,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
postgres_config_stack.add_dependency(postgresdb_stack)


# Creates all the services on ECS Fargate
# depends on all the stacks so deployed last
ecs_fargate = EcsFargateStack(app, "EcsFargateStack", 
    vpc=default_vpc.get_vpc, 
    docdb_info=documentdb_stack.docdb_info,
    pg_info=postgresdb_stack.postgres_info,
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION
    )
)
ecs_fargate.add_dependency(default_vpc)
ecs_fargate.add_dependency(documentdb_stack)
ecs_fargate.add_dependency(postgresdb_stack)


# Creates tools for developement. No need to depoly for production
# Only if needed
dev_tools = DevToolStack(app, "DevToolStack",
    ecs_info=ecs_fargate.ecs_info,
    docdb_info=documentdb_stack.docdb_info,
    vpc=default_vpc.get_vpc,
    ca_bundle_s3_uri="s3://all-purpose-utility/certs/ca-bundle.pem",
    env=cdk.Environment(
        account=cdk.Aws.ACCOUNT_ID, 
        region=cdk.Aws.REGION)
)
dev_tools.add_dependency(ecs_fargate)

app.synth()
