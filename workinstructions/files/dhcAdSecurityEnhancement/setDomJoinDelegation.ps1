<#
.SYNOPSIS
    Set s-DS-MachineAccountQuota attribute to value 0 and delegates control over computer accounts forund in ../DHC/Servers OU.
.DESCRIPTION    
    The script creates a resource group, rsce-dhc-ad-g-domainjoin, and adds as member the role grop role-$locationCode-g-platformadministrator.
    It delegates the computers accounts management \DHC\Servers OU by updating its ACL with necessary ACE rules after wich it sets 
    the ms-DS-MachineAccountQuota attribute to value 0.
    In the final part it presents the option to revert the changes made: removing ACE rules defined for resource group, set the
    ms-DS-MachineAccountQuota attribute back to value 10 and removing the resource group from AD.
.PARAMETER Path
    .
.PARAMETER LiteralPath
    .
.EXAMPLE
    .\setDomJoinDelegation -locationCode $locationCode
    .\setDomJoinDelegation -locationCode $locationCode -revert:$true    
.NOTES
    Author: Ciprian Sferle
    Date:   2024.09.13
#>


[CmdletBinding()]
Param
(
    [Parameter(Mandatory=$true)] $locationCode ,
    [Parameter(Mandatory=$false)] $revert=$false
)

Clear-Host
Set-StrictMode -Version Latest
Import-Module ActiveDirectory

[System.String] $DN = (Get-ADDomain).DistinguishedName
[System.String] $OU = "OU=Servers,OU=DHC,$DN"

[System.String] $roleGroup = "role-$locationCode-g-platformadministrators" #Role group
[System.String] $rsceGroup = "rsce-dhc-ad-g-domainjoin"                    #Resource group

if (!($revert)){

    # Check resource group existance
    try {
        Get-ADGroup -Identity $rsceGroup -ErrorAction Continue
    }
    catch {
        Write-Host "Creating resource group $rsceGroup ..." -ForegroundColor Gray
        New-ADGroup -Name $rsceGroup `
                    -DisplayName $rsceGroup `
                    -GroupCategory Security `
                    -GroupScope Global `
                    -Description "Resource Group used to domain join computer accounts" `
                    -Path "OU=ResourceGroups,OU=Groups,OU=DHC,$DN" `
                    -ManagedBy $roleGroup 
         Write-Host "Done`n" -ForegroundColor Green
         
         # Adding role group as member
         Write-Host "Adding role group $roleGroup as member of resource grou $rsceGroup" -ForegroundColor Grey
         Get-ADGroup -Identity $rsceGroup | Add-ADGroupMember -Members $roleGroup
         Write-Host "Done`n" -ForegroundColor Green
    }

    # Check group membership for resource group
    if (!(Get-ADGroupMember -Identity $rsceGroup -Recursive | 
            Where-Object Members -Contains $roleGroup |
            Select-Object Members)){
        Add-ADGroupMember -Identity $rsceGroup -Members $roleGroup
    }

    # Get the resource group SID
    $groupSID =  [System.Security.Principal.SecurityIdentifier] (Get-ADGroup -Identity $rsceGroup).sid

    # Define new ACE rules for OU
    Write-Host "Defining ACE rules for delegation" -ForegroundColor Gray
    $aceRuleSelf = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::Self,                           # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "00000000-0000-0000-0000-000000000000",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "bf967a86-0de6-11d0-a285-00aa003049e2" )                                   # InheritedObjectType

    $aceRuleSelfWriteProperty = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "00000000-0000-0000-0000-000000000000",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "bf967a86-0de6-11d0-a285-00aa003049e2" )                                   # InheritedObjectType

    $aceRuleCreateChild = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::CreateChild,                    # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "bf967a86-0de6-11d0-a285-00aa003049e2",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::All,               # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleDeleteChild = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::DeleteChild,                    # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "bf967a86-0de6-11d0-a285-00aa003049e2",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::All,               # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleCertificateAttribute = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "fa4693bb-7bc2-4cb9-81a8-c99c43b7905e",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "bf967a86-0de6-11d0-a285-00aa003049e2" )                                   # InheritedObjectType

    $aceRuleDeleteTree = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::DeleteTree,                     # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "00000000-0000-0000-0000-000000000000",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType
    
    $aceRuleExtendRight = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::ExtendedRight,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "00000000-0000-0000-0000-000000000000",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleDelete = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::Delete,                         # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "00000000-0000-0000-0000-000000000000",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleGenericRead = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::GenericRead,                    # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "00000000-0000-0000-0000-000000000000",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleUserAccountRestrictions = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "4c164200-20c0-11d0-a768-00aa006e0529",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleServerPrincipalName = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::Self,                           # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "f3a64788-5306-11d1-a9c5-0000f80367c1",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleDNSHostlName = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::Self,                           # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "72e39547-7b18-11d1-adef-00c04fd8d5cd",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleSAMAccountName = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "3e0abfd0-126a-11d0-a060-00aa006c33ed",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleDisplayName = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "bf967953-0de6-11d0-a285-00aa003049e2",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleDescription = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "bf967950-0de6-11d0-a285-00aa003049e2",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleUserLogon = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::WriteProperty,                  # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "5f202010-79a5-11d0-9020-00c04fc2d4cf",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType

    $aceRuleDSValidateWriteComputer = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
        [System.Security.Principal.IdentityReference] $groupSID,                          # IdentityReference
        [System.DirectoryServices.ActiveDirectoryRights]::Self,                           # ActiveDirectoryRights
        [System.Security.AccessControl.AccessControlType]::Allow,                         # AccessControlType
        [GUID] "9b026da6-0d3c-465c-8bee-5199d7165cba",                                    # ObjectType
        [System.DirectoryServices.ActiveDirectorySecurityInheritance]::Descendents,       # InheritanceType
        [GUID] "00000000-0000-0000-0000-000000000000" )                                   # InheritedObjectType
    Write-Host "Done`n" -ForegroundColor Green

    # Get current ACL for OU
    $ACL = Get-Acl -Path "AD:$OU"

    # Add new ACE rules to ACL
    Write-Host "Adding new ACe rules to OU's ACL" -ForegroundColor Gray
    $ACL.AddAccessRule($aceRuleSelf)
    $ACL.AddAccessRule($aceRuleSelfWriteProperty)
    $ACL.AddAccessRule($aceRuleCreateChild)
    $ACL.AddAccessRule($aceRuleDeleteChild)
    $ACL.AddAccessRule($aceRuleCertificateAttribute)
    $ACL.AddAccessRule($aceRuleDeleteTree)
    $ACL.AddAccessRule($aceRuleExtendRight)
    $ACL.AddAccessRule($aceRuleDelete)
    $ACL.AddAccessRule($aceRuleGenericRead)
    $ACL.AddAccessRule($aceRuleUserAccountRestrictions)
    $ACL.AddAccessRule($aceRuleServerPrincipalName)
    $ACL.AddAccessRule($aceRuleDNSHostlName)
    $ACL.AddAccessRule($aceRuleSAMAccountName)
    $ACL.AddAccessRule($aceRuleDisplayName)
    $ACL.AddAccessRule($aceRuleDescription)
    $ACL.AddAccessRule($aceRuleUserLogon)
    $ACL.AddAccessRule($aceRuleDSValidateWriteComputer)
    Write-Host "Done`n" -ForegroundColor Green
       
    # Push new ACL
    Write-Host "Pushing updated ACL" -ForegroundColor Gray
    Set-Acl -Path "AD:$OU" -AclObject $ACL
    Write-Host "Done`n" -ForegroundColor Green

    # Set ms-DS-MachineAccountQuota attribute to 0
    Write-Host "Setting ms-DS-MachineAccountQuota attribute to value 0" -ForegroundColor Gray
    Set-ADDomain $DN -Replace @{"ms-DS-MachineAccountQuota"="0"}
    Write-Host "Done`n" -ForegroundColor Green

    # Clear variables
    $groupSID=$null
    $ACL=$null
    $aceRuleSelf=$null
    $aceRuleSelfWriteProperty=$null
    $aceRuleCreateChild=$null
    $aceRuleDeleteChild=$null
    $aceRuleCertificateAttribute=$null
    $aceRuleDeleteTree=$null
    $aceRuleExtendRight=$null
    $aceRuleDelete=$null
    $aceRuleGenericRead=$null
    $aceRuleUserAccountRestrictions=$null
    $aceRuleServerPrincipalName=$null
    $aceRuleDNSHostlName=$null
    $aceRuleSAMAccountName=$null
    $aceRuleDisplayName=$null
    $aceRuleDescription=$null
    $aceRuleUserLogon=$null
    $aceRuleDSValidateWriteComputer=$null

    }
else {
    $groupIdentity = "$((Get-ADDomain).NetBIOSName)\$($rsceGroup)"

    # Get ACL for OU
    $ACL = Get-Acl -Path "AD:$OU"
    
    # Collect ACEs for resource group
    Write-Host "Gathering access rights assigned to $groupIdentity ..." -ForegroundColor White
    foreach($access in $ACL.Access){        
        foreach($group in $access.IdentityReference.Value){            
            if($group -eq $groupIdentity){
                $ACL.RemoveAccessRule($access) | Out-Null
            }
        }
    }
    Write-host "Done`n" -ForegroundColor Green

    # Push new ACL over OU
    Write-Host "Removing access rights assigned to $groupIdentity ..." -ForegroundColor Gray
    Set-Acl -Path "AD:$OU" -AclObject $ACL
    Write-host "Done`n" -ForegroundColor Green
    
    # Delete resource group from AD
    Write-Host "Deleting resource group $rsceGroup ..." -ForegroundColor Gray
    try {
        Remove-ADGroup -Identity $rsceGroup -Confirm:$false
        Write-host "Done`n" -ForegroundColor Green
    }
    catch {
        Write-Host "Resource group $rsceGroup already deleted!`n" -ForegroundColor DarkYellow
    }
    
    # Set value to 10 for attibute ms-DS-MachineAccountQuota
    Write-Host "Setting default value of 10 for attribute ms-DS-MachineAccountQuota ..." -ForegroundColor Gray
    Set-ADDomain $DN -Replace @{"ms-DS-MachineAccountQuota"="10"}
    Write-host "Done`n" -ForegroundColor Green

    Write-Host "Revert finished !" -ForegroundColor Green

    # Clear variables
    $groupIdentity=$null
    $ACL=$null
    $access=$null
    $group=$null

}

# Clear variables
$DN=$null
$OU=$null
$roleGroup=$null
$rsceGroup=$null