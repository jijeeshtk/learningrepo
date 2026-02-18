<#
.SYNOPSIS
    Changes the security policy values in GptTmpl.inf file
.DESCRIPTION    
    Checks and sets Security Policy values through Group Policy Object for two policies:
	- Network security: Configure encryption types allowed for Kerberos   '2147483640' (value for {AES128_HMAC_SHA1 | AES256_HMAC_SHA1 | Future encryption types})
    The functions used in this script are adapatations of ones detailed in https://stackoverflow.com/questions/23260656/modify-local-security-policy-using-powershell
.PARAMETER Path
    .
.PARAMETER LiteralPath
    .
.EXAMPLE
    .\setSecPolDcEncrypt.ps1
.NOTES
    Author: Ciprian Sferle
    Date:   2024.09.04
#>

Clear-Host
Set-StrictMode -Version Latest
Import-Module ActiveDirectory, GroupPolicy

Function ParseInf ($gptInf){
    $obj = New-Object psobject
    $index = 0
    $contents = Get-Content $gptInf -Raw
    [regex]::Matches($contents,"(?<=\[)(.*)(?=\])") | %{
        $title = $_
        [regex]::Matches($contents,"(?<=\]).*?((?=\[)|(\Z))", [System.Text.RegularExpressions.RegexOptions]::Singleline)[$index] | %{
            $section = New-Object psobject
            $_.value -split "\r\n" | ?{$_.Length -gt 0} | %{
                $value = [regex]::Match($_,"(?<=\=).*").Value
                $name = [regex]::Match($_,".*(?=\=)").Value
                $section | Add-Member -MemberType NoteProperty -Name $name.ToString().Trim() -Value $value.ToString().Trim() -ErrorAction SilentlyContinue | Out-Null
            }
            $obj | Add-Member -MemberType NoteProperty -Name $title -Value $section
        }
        $index += 1
    }
    return $obj
}

Function SetInf($object, $gptFile){
    $object.psobject.Properties.GetEnumerator() | %{
        "[$($_.Name)]"
        $_.Value | %{
            $_.psobject.Properties.GetEnumerator() | %{
                "$($_.Name)=$($_.Value)"
            }
        }
    } | Out-File $gptFile -ErrorAction Stop -Encoding unicode
}

[System.String] $DN=(Get-ADDomain).DistinguishedName
[System.String] $DNS=(Get-ADDomain).DNSRoot
[System.String] $DC=(Get-ADDomainController -Discover -NextClosestSite).Name
[System.Boolean] $gptModified = $false

<# Registry value types
    0   REG_NONE
    1   REG_SZ
    2   REG_EXPAND_SZ
    3   REG_BINARY
    4   REG_DWORD / REG_DWORD_LITTLE_ENDIAN
    5   REG_DWORD_BIG_ENDIAN
    6   REG_LINK
    7   REG_MULTI_SZ
    8	REG_RESOURCE_LIST
    9	REG_FULL_RESOURCE_DESCRIPTOR
    10	REG_RESOURCE_REQUIREMENTS_LIST
    11	REG_QWORD / REG_QWORD_LITTLE_ENDIAN
#>

$gpoPol = @(
    New-Object psobject -Property @{Name = 'Network security: Configure encryption types allowed for Kerberos';
      Key = 'MACHINE\Software\Microsoft\Windows\CurrentVersion\Policies\System\Kerberos\Parameters\SupportedEncryptionTypes';
      Value = '2147483640';
      Type = '4' }
)

#Get a list of GPOs from the domain
$GPOs = Get-GPO -All -Domain $DNS -Server $DC | Sort-Object DisplayName

#Go through each Object and check its XML against $String
Foreach ($gpo in $GPOs){

    #Get Current GPO Report (XML)
    $CurrentGPOReport = Get-GPOReport -Guid $gpo.Id -ReportType Xml -Domain $DNS -Server $DC

    $gpoPol | ForEach-Object {
    
        #Search policy in GPO report
        If ($CurrentGPOReport -match $_.Name){

            #GPO linked OU
            try {
                $linkedOU=(Get-ADOrganizationalUnit -SearchBase $DN -SearchScope Subtree -Filter * -Properties * | 
                    Where-Object LinkedGroupPolicyObjects -Like "*$($gpo.Id)*" |
                    Select-Object CanonicalName).CanonicalName
                    Write-Host "`tGPO Linked OU:`t$($linkedOU)"

                if ($linkedOU -ne $null){
                    #Define GPO folder path in SYSVOL
                    [System.String] $gptPath = "\\$DNS\sysvol\$DNS\Policies\{$($gpo.id)}"

                    #Get the inf file path from the GPO folder path
                    $gptTmpl = Get-ChildItem -Path $gptPath -Include *.inf -Recurse

                    #Parse GptTmpl.inf file to a workable format
                    $gptOut = ParseInf($gptTmpl)

                    #Check for key values and modify if needed
                    if (!($gptOut.'Registry Values'.$($_.Key) -eq "$($_.Type),$($_.Value)")){
                        $gptOut.'Registry Values'.$($_.Key) ="$($_.Type),$($_.Value)"
                        $gptModified = $true
                    }
                }
            }
            catch {
            }

            #Check if existing values were modified and push new file if needed
            if($gptModified) {
                SetInf -Object $gptOut -gptFile $gptTmpl.FullName
            }
            
            #Cleare variables/objects
            $linkedOU=$null
            $gptPath=$null
            $gptTmpl=$null
            $gptOut=$null
            $gptModified=$false
        }
    }
    $CurrentGPOReport=$null
}
$GPOs=$null
$gpo=$null
$gpoPol=$null