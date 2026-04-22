output "app_name" {
  value = juju_application.grafana_agent.name
}

output "provides" {
  value = {
    grafana_dashboards_provider = "grafana-dashboards-provider"
  }
}

output "requires" {
  value = {
    certificates         = "certificates"
    juju_info            = "juju-info"
    cos_agent            = "cos-agent"
    send_remote_write    = "send-remote-write"
    logging_consumer     = "logging-consumer"
    grafana_cloud_config = "grafana-cloud-config"
    receive_ca_cert      = "receive-ca-cert"
    tracing              = "tracing"
  }
}
