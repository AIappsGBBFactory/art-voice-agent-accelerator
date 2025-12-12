# Issues Discussed *With Associated Images* During Session

## 1. Pre‑provision Script Error — Docker / Intermittent Failure
**Issue:** Pre-provision step fails when Docker Desktop wasn’t actually running.  
**Resolution:** Restart Docker Desktop; run `azd up` from Git Bash or WSL instead of Windows Terminal.

## 2. `jq` Not Found (`command not found`)
**Issue:** `preprovision.sh` fails with `jq: command not found` → exit code 127.  
**Resolution:** Install `jq` (winget or package manager); ensure PATH updates correctly.

## 3. ACS Phone Number Prompt Confusion
**Issue:** Unsure whether to “provision new or skip” when prompted for `ACS_SOURCE_PHONE_NUMBER`.  
**Resolution:** Choose option **2** → azd will automatically provision an ACS resource and phone number.

## 4. MissingSubscriptionRegistration — `Microsoft.Communication`
**Issue:** Terraform fails creating Email Communication Service with  
`MissingSubscriptionRegistration: The subscription is not registered to use namespace 'Microsoft.Communication'`.  
**Resolution:**  
```bash
az provider register --namespace Microsoft.Communication
````

## 5. Backend Runtime Health Check Errors

**Issue:** Backend endpoint showing unhealthy/failed status.  
**Resolution:** Likely early-stage deployment timing or environment setup not finished.

## 6. Another `jq` Provisioning Failure

**Issue:** Similar `jq`-related pipeline failure.  
**Resolution:** Reinstall `jq` and verify PATH.

## 7. Missing Subscription Value During Pre‑provision

**Image:** Kira Soderstrom (msg #40)  
**Issue:** Pre-provision script fails due to missing subscription context.  
**Resolution:**

```bash
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

## 8. Cosmos DB & AOAI Quota Errors

**Issue:** Model `gpt-realtime` not available / requires quota.  
**Resolution:** Switch to **East US 2** or request quota increase.

## 9. `dos2unix` / Windows Line Ending Errors

**Issue:** Pre-provision script failing due to Windows CRLF line endings.  
**Resolution:**

```bash
dos2unix <script>
```

## 10. Authentication / Subscription Missing

**Issue:** CLI reports the subscription is missing even after `az login` and `azd auth login`.  
**Resolution:** Verify active subscription:

```bash
az account show
```

## 11. Terraform Missing `main.tfvars.json`

**Issue:** Terraform fails with  
`open ... main.tfvars.json: The system cannot find the file specified.`  
**Resolution:** Re-clone repo or restore infra folder.

## 12. Storage Container Provisioning Delay Issues

**Issue:** First run of `azd up` fails with 403 due to storage container not yet fully provisioned.  
**Resolution:** Rerun `azd up` after short wait; add delay in script.

```

If you want, I can also generate:

✅ A **markdown table**  
✅ A **slide‑ready outline**  
✅ An **issue → root cause matrix**  
```
