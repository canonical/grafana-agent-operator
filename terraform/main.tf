resource "juju_application" "grafana_agent" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  storage_directives = var.storage_directives
  trust              = true # We always need this variable to be true in order to be able to apply resources limits. 
  units              = var.units

  charm {
    name     = "grafana-agent"
    channel  = var.channel
    revision = var.revision
  }
}
