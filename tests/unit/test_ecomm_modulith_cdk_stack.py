import aws_cdk as core
import aws_cdk.assertions as assertions

from ecomm_modulith_cdk.ecomm_modulith_cdk_stack import EcommModulithCdkStack

# example tests. To run these tests, uncomment this file along with the example
# resource in ecomm_modulith_cdk/ecomm_modulith_cdk_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = EcommModulithCdkStack(app, "ecomm-modulith-cdk")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
