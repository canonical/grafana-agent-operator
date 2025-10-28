# Terraform module for grafana-agent


This is a Terraform module facilitating the deployment of grafana-agent charm, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs).

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.5 |
| <a name="requirement_juju"></a> [juju](#requirement\_juju) | < 1.0.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_juju"></a> [juju](#provider\_juju) | < 1.0.0 |

## Modules

No modules.

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_app_name"></a> [app\_name](#input\_app\_name) | Application name | `string` | n/a | yes |
| <a name="input_channel"></a> [channel](#input\_channel) | Charm channel | `string` | `"latest/stable"` | no |
| <a name="input_config"></a> [config](#input\_config) | Config options as in the ones we pass in juju config | `map(string)` | `{}` | no |
| <a name="input_constraints"></a> [constraints](#input\_constraints) | Constraints to be applied | `string` | `""` | no |
| <a name="input_model_name"></a> [model\_name](#input\_model\_name) | Model name | `string` | n/a | yes |
| <a name="input_revision"></a> [revision](#input\_revision) | Charm revision | `number` | `null` | no |
| <a name="input_units"></a> [units](#input\_units) | Number of units | `number` | `1` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_app_name"></a> [app\_name](#output\_app\_name) | n/a |
<!-- END_TF_DOCS -->
