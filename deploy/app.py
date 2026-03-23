#!/usr/bin/env python3
"""CDK app entry point for ezchat infrastructure."""
import aws_cdk as cdk

from ezchat_stack import EzchatStack

app = cdk.App()
EzchatStack(app, "EzchatStack",
    env=cdk.Environment(
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)
app.synth()
