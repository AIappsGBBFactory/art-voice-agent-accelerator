# :material-connection: Integrations Overview

This section covers integrations between the Azure Real-Time Voice Agent and various telephony and contact center platforms.

---

## :material-format-list-bulleted: Available Integrations

### :material-phone-forward: Direct Routing
Connect your existing on-premises or cloud-based telephony infrastructure to Azure Communication Services using Session Border Controllers (SBCs).

[:material-arrow-right: Learn about Direct Routing](directrouting.md){ .md-button }

---

### :material-microsoft-dynamics-365: Dynamics 365
Integrate with Microsoft Dynamics 365 Customer Service for seamless voice agent capabilities within your CRM workflows.

[:material-arrow-right: Dynamics 365 Integration](dynamics.md){ .md-button }

---

### :material-phone-voip: Genesys Cloud
Connect your Genesys Cloud contact center platform with Azure AI voice agents for enhanced customer experiences.

[:material-arrow-right: Genesys Cloud Integration](genesys.md){ .md-button }

---

## :material-lightbulb: Integration Patterns

All integrations follow similar architectural patterns:

1. **Telephony Connection**: Establish SIP connectivity between platforms
2. **Event Webhooks**: Receive call events and routing decisions
3. **Media Streaming**: Real-time audio exchange via WebSocket or RTP
4. **State Synchronization**: Maintain call context across systems
5. **Transfer Capabilities**: Seamless handoff between AI and human agents

---

## :material-help-circle: Need Help?

For assistance with integrations:

- Review the specific integration guide for your platform
- Check the [Troubleshooting Guide](../operations/troubleshooting.md)
- Consult Azure Communication Services documentation
- Contact your platform vendor for SBC/connector support
