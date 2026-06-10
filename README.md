# AWS Infrastructure for the Modular Monolith
## Overview

This project contains the AWS Cloud Development Kit (CDK) infrastructure used to deploy and operate the E-Commerce Modular Monolith application.

## Design Goal

This main goal of the project was to simplify the first Ecomm App that started as simple
service that grew into a complex mesh of services, resources and cost which really out
weighed the application load.

Rather than maintaining numerous independent microservices and supporting infrastructure like in the
first microservices Ecomm App, this application is deployed as a single containerized Spring Modulith application running on Amazon ECS Fargate.

Infrastructure is defined entirely as code using AWS CDK, enabling repeatable deployments, environment consistency, and automated provisioning.


```
                        Internet
                            │
                            ▼

                 Application Load Balancer
                            │
                            ▼

                    ECS Fargate Service
                     Spring Modulith
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼

    PostgreSQL RDS                   Amazon DocumentDB

                            ▲
                            │
                  Development Tools Stack
                         (Optional)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼

        Mongo Express           Development SMTP
```

## Infrastructure Stacks
### VPC Stack

The VPC stack creates the foundational networking environment used by all other infrastructure components.

Responsibilities include:

* Virtual Private Cloud (VPC)
* Public subnets
* Private subnets
* Security groups
* Network isolation

All application resources are deployed within this VPC.

### DocumentDB Stack

The DocumentDB stack provisions the document database used by selected application modules.

Responsibilities include:

* Amazon DocumentDB cluster
* Database security configuration
* Secrets management
* Private network access

DocumentDB is used for modules that benefit from flexible document storage.
* Customer data
* Notifications

This allows the application to leverage both relational and document database patterns where appropriate.


### PostgreSQL RDS Stack

The PostgreSQL stack provisions the relational database used by the application.

Responsibilities include:

* Amazon RDS PostgreSQL serverless
* Database credentials management
* Security group configuration
* Automated backups
* Private network access

The relational database stores business-critical transactional data such as:

* Orders
* Payments
* Products
* Shipments
* Security and user information

### Database Initialization Stack

A dedicated stack uses AWS Lambda to automate database creation and initialization.

Responsibilities include:

* Creating application databases
* Creating schemas
* Executing initialization scripts
* Establishing required database structure

This eliminates manual database setup steps and ensures consistent environments across deployments.

### Why Lambda?

Using Lambda allows infrastructure deployment to:

* Provision the database
* Wait for availability
* Automatically create schemas and tables
* Complete deployment without manual intervention

This approach supports fully automated infrastructure provisioning.


### ECS Fargate Stack

The ECS stack hosts the Spring Modulith application.

Responsibilities include:

* ECS Cluster
* Fargate Service
* Task Definitions
* Application Load Balancer
* Auto-scaling configuration
* Container deployment

The modular monolith is packaged as a Docker container and deployed as a single application instance.


### Benefits
* No server management
* Simplified deployments
* Automatic scaling
* High availability
* Reduced operational overhead


### Deployment Flow
```
CDK Deployment
      │
      ▼

VPC Stack
      │
      ▼

DocumenDb Stack
      │
      ▼

Postgres Database Stack
      │
      ▼

Postgres Configuration Stack
      │
      ▼

ECS Fargate Stack
      │
      ▼

Optional-DevTools Stack
      │
      ▼

Application Available
```

Each stack builds upon infrastructure provisioned by previous stacks, ensuring resources are deployed in the correct order.


### Security

Security is implemented through multiple layers:

* Network Security
* Private database subnets
* Restricted security groups
* Internal database communication
### Secrets Management

Sensitive configuration is stored in AWS Secrets Manager, including:

* PostgreSQL credentials
* DocumentDB credentials
* Github container registry credentials

### Container Security
* Non-public database access
* IAM task roles
* Principle of least privilege


### CI/CD Integration

Infrastructure is deployed using GitHub Actions and AWS CDK.

Deployment automation includes:
* Container image publishing


This enables fully automated deployments from source control to production.


### Technology Stack
### Infrastructure as Code
* AWS CDK
* Python

### Compute
* Amazon ECS
* AWS Fargate
* AWS Lambda

### Databases
* Amazon RDS PostgreSQL
* Amazon DocumentDB

### Networking
* Amazon VPC
* Application Load Balancer
### Security
* AWS Secrets Manager
* IAM
* Security Groups




