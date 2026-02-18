$results=@() 
$vCenterIP = "vCenterFQDN1","vCenterFQDN2"
$date = Get-Date -format dd.MM.yyyy
$path = "D:\Scripts\vSAN\DHC-<customerCode>-<locationCode>-vSAN-$date.csv"
$users = "emailid"  # List of users to email your report to (separate by comma)
$fromemail = "noreply@atos.net"
$smtpserver = "smtpserver" # provide SMTP Server Name
Disconnect-VIServer -Confirm:$False -ErrorAction SilentlyContinue

foreach ($vc in $vCenterIP)
{
Connect-VIServer $vc

$clusterforVsan = (get-cluster).Name
foreach ($ClusterName in $clusterforVsan)
{
$vsandiskgroup = Get-VsanDiskGroup -Cluster $ClusterName
$StorageBeforeFTT = 0
foreach ($disk in $vsandiskgroup)
{
$vsdisk = Get-VsanDisk -VsanDiskGroup $disk
foreach ($vsd in $vsdisk)
{
$disksize =$vsd.CapacityGB
$StorageBeforeFTT = $StorageBeforeFTT + $disksize
}
}

$datastores = get-datastore -name *vsan* -RelatedObject $ClusterName | get-view -ErrorAction Continue
$pro = $datastores | select -expandproperty summary | select @{N="Capacity (GB)"; E={[math]::round($_.Capacity/1GB,2)}}, @{N="FreeSpace (GB)"; E={[math]::round($_.FreeSpace/1GB,2)}}, @{N="ProvisionedSpace"; E={[math]::round(($_.Capacity - $_.FreeSpace + $_.Uncommitted)/1GB,2) }}  #| sort -Property Name | Export-Csv C:\Users\a612571\Downloads\all.csv -NoTypeInformation
$DTproSpace = $pro.ProvisionedSpace

[String]$DTName = (get-datastore -name *vsan* -RelatedObject $ClusterName).Name
[int32]$dtCapacity = (get-datastore -name *vsan* -RelatedObject $ClusterName).CapacityGB
[int32]$DTFreeSpace = (get-datastore -name *vsan* -RelatedObject $ClusterName).FreeSpaceGB
[int32]$DTUsedSpace = $dtCapacity - $DTFreeSpace
$DTUsedPercentage = $DTUsedSpace / $dtCapacity * 100
$DTFreePercentage = $DTFreeSpace / $dtCapacity * 100
$DTProPercentage = $DTproSpace / $dtCapacity * 100

$Cluster = ((Get-VsanClusterConfiguration).PerformanceStatsStoragePolicy).Name

$ftt = (Get-SpbmStoragePolicy -Name $Cluster).AnyOfRuleSets
[String]$fttdetails = $ftt
$vsanFtt = $fttdetails.Substring($fttdetails.IndexOf('VSAN.hostFailuresToTolerate')+28, 1)
$vsanFtmchk = $fttdetails.Substring($fttdetails.IndexOf('VSAN.replicaPreference')+23, 6)
if ($vsanFtmchk -eq "RAID-1" -or $vsanFtmchk -eq "RAID-5" -or $vsanFtmchk -eq "RAID-6")
{ 
$vsanFtm = $vsanFtmchk
}
else
{
$vsanFtm = "RAID-1"
}

if ($vsanFtt -eq 1 -and $vsanFtm -eq "RAID-1")
{
$capacityFactor = 50
}
elseif($vsanFtt -eq 2 -and $vsanFtm -eq "RAID-1")
{
$capacityFactor = 33
}
elseif($vsanFtt -eq 3 -and $vsanFtm -eq "RAID-1")
{
$capacityFactor = 25
}
elseif ($vsanFtt -eq 1 -and $vsanFtm -ne "RAID-1")
{
$capacityFactor = 75
}
elseif ($vsanFtt -eq 2 -and $vsanFtm -ne "RAID-1")
{
$capacityFactor = 67
}
else
{
$capacityFactor = 100
}

$capacityAfterFTT = $dtCapacity * $capacityFactor / 100
$freeAfterFTT = $DTFreeSpace * $capacityFactor / 100
$freeAfterFTTper = $freeAfterFTT / $dtCapacity * 100

$details = New-Object PSObject
$details | Add-Member -MemberType NoteProperty -Name "DataStore Name" -Value $DTName
$details | Add-Member -MemberType NoteProperty -Name "Installed RAWCap [GB]" -Value $StorageBeforeFTT
$details | Add-Member -MemberType NoteProperty -Name "Total AvailableCap [GB]" -Value $dtCapacity
$details | Add-Member -MemberType NoteProperty -Name "FreeCap after FTT & FTM [GBu]" -Value $freeAfterFTT
$details | Add-Member -MemberType NoteProperty -Name "FreeCap after FTT & FTM [%]" -Value $freeAfterFTTper
$details | Add-Member -MemberType NoteProperty -Name "UsedCap [GBu]" -Value $DTUsedSpace
$details | Add-Member -MemberType NoteProperty -Name "UsedCap after FTT & FTM  [%]" -Value $DTUsedPercentage
$details | Add-Member -MemberType NoteProperty -Name "ProvisionedCap [GBe]" -Value $DTproSpace
$details | Add-Member -MemberType NoteProperty -Name "ProvisionedCap [%]" -Value $DTProPercentage
$details | Add-Member -MemberType NoteProperty -Name "FreeCap before FTT & FTM [GB]" -Value $DTFreeSpace
$details | Add-Member -MemberType NoteProperty -Name "FreeCap before FTT & FTM [%]" -Value $DTFreePercentage
$details | Add-Member -MemberType NoteProperty -Name "FTT Of Datastore" -Value $vsanFtt
$details | Add-Member -MemberType NoteProperty -Name "FTM Of Datastore" -Value $vsanFtm


$results += $details
}
Disconnect-VIServer -Confirm:$False -ErrorAction SilentlyContinue
}
$results | export-csv -Path $path -NoTypeInformation

#Send Mail
    send-mailmessage -from $fromemail -to $users -subject "VSAN Report" -Attachments $path -priority High -smtpServer $smtpserver
