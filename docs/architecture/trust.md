# Understand identity and access

A bearer token authenticates one Carrier inbox. Local provisioning is an operator
capability; ordinary HTTP clients cannot create an identity.

```mermaid
sequenceDiagram
  accTitle: Authenticate an inbox operation
  accDescr: An operator provisions the served database and a private credential file. A client sends its bearer token; the service hashes it and restricts inbox operations to the resulting identity.
  participant Operator
  participant DB as SQLite
  participant Client
  participant Service
  Operator->>DB: Provision address and token hash
  Operator->>Client: Private address and token file
  Client->>Service: Bearer token and operation
  Service->>DB: Resolve hash to identity
  DB-->>Service: Authenticated address
  Service-->>Client: Identity-scoped result
```

| Boundary | Contract |
| --- | --- |
| Credentials | Keep tokens private; sharing a file shares that inbox's authority |
| Directory | Authenticated clients can list addresses and display names |
| Inbox/history/ack | Restricted to the authenticated recipient |
| Sent history/delivery status | Restricted to the authenticated sender |
| Names | Case-sensitive, non-unique labels; ambiguity returns 409 |
| Health | Public health response establishes service availability, not inbox access |
| Network | Loopback by default; remote operation needs separately reviewed HTTPS and deployment controls |

Use `carrier session` once for manual setup. On supported Unix systems,
`ensure_session()` preserves credentials and recovers interrupted provisioning
with a pending file and lock. Point it at the database actually served, then
verify through `Client.open()`. It does not provision a remote database.

The optional agent adapter adds conversation ownership gating. That gate does not
replace HTTP authentication or grant provider permissions.

Sources: [identity and route checks](../../carrier/service.py),
[provisioning](../../carrier/provision.py), [binding](../../carrier/integrations/agent_manager/binding.py).
