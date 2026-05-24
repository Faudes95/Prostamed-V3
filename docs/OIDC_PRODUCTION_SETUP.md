# OIDC Production Setup — ProstaNet Multi-Site Pilot

> Sprint 7.B · FAUBOT CXLV · Foundation para piloto multi-sitio (visión H3)

## Por qué OIDC en producción

`LocalPbkdf2Backend` (default) funciona para single-site con usernames locales. Para piloto multi-sitio (México + Colombia + Perú), cada hospital tiene su Active Directory institucional + políticas de MFA/rotation. Sin OIDC, ProstaNet duplica gestión de identidad → friccion de adopción.

OIDC entrega:
- **SSO institucional** — clínico usa credenciales hospital ya existentes
- **MFA out-of-the-box** — Auth0/Keycloak configuran sin tocar ProstaNet
- **Role mapping centralizado** — admin/clinician asignados desde IDP
- **Token rotation + refresh** — sesiones seguras sin password reuse
- **Federated learning foundation** — cada sitio mantiene PHI local

---

## Arquitectura

```
Hospital IDP (Auth0/Keycloak/Azure AD)
        ↓ OIDC Authorization Code + PKCE
ProstaNet /api/auth/oidc/login   →   redirect IDP
ProstaNet /api/auth/oidc/callback ← code + state
        ↓ token exchange + userinfo
JIT provision en clinical_users (backend='oidc', external_id=issuer|sub)
        ↓ role mapping desde claims (realm_access, custom namespace)
api_auth.@require_clinician / @require_admin ← lee role de clinical_users
```

---

## Configuración — Auth0 (recomendado SaaS)

### 1. Crear Application en Auth0

1. Auth0 Dashboard → **Applications** → **Create Application**
2. Name: `ProstaNet Clinical Hub`
3. Type: **Regular Web Application**
4. Click **Create**

### 2. Configurar URIs

En **Settings**:
- **Allowed Callback URLs**: `https://prostanet.your-hospital.mx/api/auth/oidc/callback`
- **Allowed Logout URLs**: `https://prostanet.your-hospital.mx/`
- **Allowed Web Origins**: `https://prostanet.your-hospital.mx`

### 3. Habilitar PKCE (obligatorio Sprint 6)

**Settings → Advanced → OAuth**:
- **OIDC Conformant**: ON
- **Allowed Response Types**: `code` (sin `token`/`id_token` — usamos code flow)

### 4. Custom claims para role mapping

Auth0 → **Actions** → **Flows** → **Login** → **+ Create Action**:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const roles = (event.authorization?.roles || []);
  // Mapear roles institucionales a roles ProstaNet
  const prostanet_roles = roles
    .map(r => r.toLowerCase())
    .filter(r => ['admin', 'physician', 'clinician', 'researcher'].includes(r));

  if (prostanet_roles.length === 0) {
    prostanet_roles.push('clinician');  // default
  }

  // Custom namespaced claim — leído por OidcBackend._role_from_userinfo
  api.idToken.setCustomClaim('https://prostanet/roles', prostanet_roles);
  api.accessToken.setCustomClaim('https://prostanet/roles', prostanet_roles);
};
```

Click **Deploy** + arrastrar al Login flow.

### 5. Configurar env vars en ProstaNet

```bash
# /etc/prostanet/env (o similar)
PROSTANET_AUTH_BACKEND=auth0
PROSTANET_OIDC_ISSUER=https://your-tenant.auth0.com/
PROSTANET_OIDC_CLIENT_ID=AbC123XyZ...
PROSTANET_OIDC_CLIENT_SECRET=<from Auth0 Application > Settings>
PROSTANET_OIDC_REDIRECT_URI=https://prostanet.your-hospital.mx/api/auth/oidc/callback
PROSTANET_OIDC_SCOPE=openid email profile roles
PROSTANET_OIDC_DEFAULT_ROLE=clinician
```

### 6. Verificar setup

```bash
curl https://prostanet.your-hospital.mx/api/auth/oidc/status | jq
```

Expected `200 OK`:
```json
{
  "success": true,
  "backend_active": "auth0",
  "is_oidc_backend": true,
  "configured": true,
  "issuer": "https://your-tenant.auth0.com/",
  "client_id_set": true,
  "discovery_reachable": true,
  "discovery_endpoints": {
    "authorization": "...",
    "token": "...",
    "userinfo": "...",
    "jwks": "..."
  },
  "oidc_users_count": 0,
  "recent_oidc_provisions": []
}
```

### 7. Probar login flow

Browser → `https://prostanet.your-hospital.mx/api/auth/oidc/login`
→ redirect a Auth0 Universal Login
→ autenticar con credenciales hospital
→ redirect back a ProstaNet
→ check `/api/auth/whoami` debe devolver `user_id` + `role`

---

## Configuración — Keycloak (self-hosted on-premise)

### 1. Crear Realm

1. Keycloak Admin → **Add Realm** → name: `prostanet-pilot`

### 2. Crear Client

**Clients → Create**:
- Client ID: `prostanet-app`
- Protocol: `openid-connect`
- Access Type: `confidential` (genera client secret)
- Standard Flow Enabled: ON
- Valid Redirect URIs: `https://prostanet.your-hospital.mx/api/auth/oidc/callback`
- Web Origins: `https://prostanet.your-hospital.mx`

### 3. Configurar Realm Roles

**Realm Roles → Add Role**: crear `admin`, `clinician`, `physician`, `researcher`.

**Users → <user> → Role Mappings**: asignar `clinician` a usuarios estándar; `admin` a quienes pueden ejecutar mutaciones poblacionales.

### 4. Env vars

```bash
PROSTANET_AUTH_BACKEND=keycloak
PROSTANET_OIDC_ISSUER=https://keycloak.your-hospital.mx/auth/realms/prostanet-pilot
PROSTANET_OIDC_CLIENT_ID=prostanet-app
PROSTANET_OIDC_CLIENT_SECRET=<from Clients > prostanet-app > Credentials>
PROSTANET_OIDC_REDIRECT_URI=https://prostanet.your-hospital.mx/api/auth/oidc/callback
PROSTANET_OIDC_SCOPE=openid email profile
PROSTANET_OIDC_DEFAULT_ROLE=clinician
```

Keycloak entrega `realm_access.roles` automáticamente — `OidcBackend._role_from_userinfo` ya lo lee (Sprint 7.B).

---

## Verificación post-setup

| Check | Comando | Esperado |
|---|---|---|
| Backend reportado | `curl .../api/auth/oidc/status` | `is_oidc_backend: true` |
| Discovery reachable | (mismo) | `discovery_reachable: true` |
| Login flow | Browser visit `/api/auth/oidc/login` | Redirect a IDP |
| Callback success | Browser tras autenticar | Cookie set + redirect home |
| Role mapping | `curl -b cookie.txt .../api/auth/whoami` | `role: clinician` (o admin) |
| Protected endpoint | `curl -b cookie.txt .../api/trajectory/<nss>` | 200 (no 401) |

---

## Rollback

Si OIDC falla en producción, rollback inmediato a PBKDF2:

```bash
export PROSTANET_AUTH_BACKEND=local
# restart server — endpoints siguen funcionando con users locales
```

Los OIDC users JIT-provisioned permanecen en `clinical_users` (backend='oidc', password_hash=''), inactivos hasta restablecer OIDC.

---

## Migración progresiva

Recomendación para piloto:
1. **Fase 0** (días 0-7): OIDC en STAGING — admin tester verifica login + roles
2. **Fase 1** (días 7-21): OIDC en PROD pero `PROSTANET_AUTH_BACKEND=local` aún. Solo admin usa OIDC via override env. Demás clínicos PBKDF2.
3. **Fase 2** (día 21+): Switch global `PROSTANET_AUTH_BACKEND=oidc`. Comunicar a clínicos: usar SSO institucional. PBKDF2 deprecated.
4. **Fase 3** (día 60+): disable PBKDF2 backend — todos los users via OIDC.

---

## Troubleshooting

| Síntoma | Diagnóstico | Fix |
|---|---|---|
| `/oidc/status` reporta `configured: false` | Env vars missing | Set ISSUER + CLIENT_ID + CLIENT_SECRET |
| `discovery_reachable: false` | IDP URL incorrecto o network | Verificar issuer + firewall |
| Callback 400 "state mismatch" | Session cookie no propagada | Verificar PROSTANET_SECRET_KEY estable + SameSite |
| Login OK pero role 'clinician' siempre | Claims no incluyen roles | Verificar Action Auth0 / Keycloak Realm Roles |
| `oidc_users_count: 0` después de login | JIT provision falló | Check log `OIDC JIT provision` |

---

## Foundation Sprint 8+

Con OIDC en producción multi-sitio:
- **Federated learning**: cada sitio mantiene PHI local, comparte solo agregados firmados con OIDC scope `prostanet:federated_aggregate`
- **Tumor board distribuido**: consenso entre 3 hospitales sobre 1 caso, cada participante autenticado por su IDP propio
- **Patient-facing view**: paciente accede con OIDC propio (Google/Apple/MX-ID), no requiere cuenta separada
