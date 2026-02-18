#Command line parameters
[CmdletBinding()]
 [string]$hostIP = "vCenterFQDN" # provide vCenter Name
 [string]$sortBy = "Name"
 $date = Get-Date -format ddMMyyyy
 $users = "useremail@atos.net"  # List of users to email your report to (separate by comma)
 $fromemail = "noreply@atos.net"
 $smtpserver = "SMTPFQDN" # provide SMTP Server Name
#)

#Populate PSObject with the required vm properties 
function vmProperties
{
 param([PSObject]$view)
 
 $list=foreach ($vm in $view)
 {
 
 #Get net info
  $ips=$vm.guest.net.ipaddress
  $macs=$vm.guest.net.MacAddress
  $VMname = $vm.Name
 
 #State info
  if ($vm.Runtime.PowerState -eq "poweredOn") {$state="ON"}
   elseif ($vm.Runtime.PowerState -eq "poweredOff") {$state="OFF"}
    else {$state="n/a"}
 
 #VMtools state
  if ($vm.summary.guest.ToolsRunningStatus -eq "guestToolsRunning") {$vmtools="Running"}
   elseif ($vm.summary.guest.ToolsRunningStatus -eq "guestToolsNotRunning") {$vmtools="Not running"}
    else {$vmtools="n/a"}
 
 #Check for multi-homed vms - max. 2 ips
  if ($ips.count -gt 1)
  {$ips=$vm.guest.net.ipaddress[0] + " " + $vm.guest.net.ipaddress[1]} 
 
  if ($macs.count -gt 1)
   {$macs=$vm.guest.net.macaddress[0] + " " + $vm.guest.net.macaddress[1]} 
 

 #Check Disaster Recovery Status
 if( $VMname -eq "DPC.Next_Linux" -or $VMname -eq "GlobalImage_w2k16" -or $VMname -eq "cisnext-win2019-se" -or $VMname -eq "cisnext-win2019-de" -or $VMname -eq "cisnext-win2016-se" -or $VMname -eq "cisnext-win2016-de" -or $VMname -eq "cisnext-win2012r2-se" -or $VMname -eq "cisnext-win2012r2-de")
 {
 $DRStatus = "Its Template"
 }
  else
 { 
   $drcheck = get-VM $VMname | Get-TagAssignment
   $vmdrcheck = $drcheck.tag |  where {$_.Category -like 'UHC-SN-DISASTER_RECOVERY'}
   
   $vmdrcheck1 = $vmdrcheck.name
    if($vmdrcheck1 -eq "yes" )
    {
     $DRStatus = "DR Protected"
    }
    else
    {
     $DRStatus = "Not Protected"
    }
    } 
   
 #Calculate Storage as per policy
 $GoldStorage = 0
 $SilverStorage = 0
 $NoPolicy = 0
 if( $VMname -eq "DPC.Next_Linux" -or $VMname -eq "GlobalImage_w2k16" -or $VMname -eq "cisnext-win2019-se" -or $VMname -eq "cisnext-win2019-de" -or $VMname -eq "cisnext-win2016-se" -or $VMname -eq "cisnext-win2016-de" -or $VMname -eq "cisnext-win2012r2-se" -or $VMname -eq "cisnext-win2012r2-de")
 {
 $NoPolicy = 0
 }
  else
 {
 $GoldPolicy = "Management Storage Policy - Regular"
 $SilverPolicy = "Management Storage Policy - Thin"
 $hm = Get-HardDisk -VM $VMname -ErrorAction Ignore
 $hdid = ($hm).id
 foreach($h in $hdid)
  {
   $hddt = Get-VM -Name $VMname | Get-Harddisk -Id $h -ErrorAction Continue
   $hdpolicy = ((Get-VM -Name $VMname | Get-Harddisk -Id $h | Get-SpbmEntityConfiguration -ErrorAction Continue).StoragePolicy).name
   $hdsize = $hddt.CapacityGB
   
   if ($hdpolicy -eq $GoldPolicy )
      {
       $GoldStorage = $GoldStorage + $hdsize
      }
   elseif ($hdpolicy -eq $SilverPolicy)
      {
       $SilverStorage = $SilverStorage + $hdsize
      }
   else
      {
       $NoPolicy = $NoPolicy + $hdsize
      }
   }
   }

 #Get VM ownership details
 if( $VMname -eq "DPC.Next_Linux" -or $VMname -eq "GlobalImage_w2k16" -or $VMname -eq "cisnext-win2019-se" -or $VMname -eq "cisnext-win2019-de" -or $VMname -eq "cisnext-win2016-se" -or $VMname -eq "cisnext-win2016-de" -or $VMname -eq "cisnext-win2012r2-se" -or $VMname -eq "cisnext-win2012r2-de")
 {
 $vmtag = "Its Template"
 }
  else
 {
   $tagcheck = get-VM $VMname | Get-TagAssignment
   $vmtagcheck = $tagcheck.Tag |  where {$_.Category -like 'managedOs*'}
   $vmtagcheck1 = $vmtagcheck.Name
    if($vmtagcheck1 -eq "atos" )
    {
     $vmtag = "ATOS Managed"
    }
    elseif($vmtagcheck1 -eq "akzo" )
    { 
     $vmtag = "Customer Managed"
    }
    else
    {
     $vmtag = "Information not available"
    }
    }
 
 #Populate object
 [PSCustomObject]@{
  "Name" = $vm.Name
  "OS" = $vm.Guest.GuestFullName
  "Hostname" = $vm.summary.guest.hostname
  "vCPUs" = $vm.Config.hardware.NumCPU
  #"Cores" = $vm.Config.Hardware.NumCoresPerSocket
  "Memory" = $vm.Config.Hardware.MemoryMB
  #"RAM Host" = $vm.summary.QuickStats.HostMemoryUsage
  #"RAM guest" = $vm.summary.QuickStats.GuestMemoryUsage
  "NICS" = $vm.Summary.config.NumEthernetCards
  "IPs" = $ips
  #"MACs" = $macs
  "vmTools" = $vmtools
  "State" = $state
  #"UUID" = $vm.Summary.config.Uuid
  #"VM ID" = $vm.Summary.vm.value
  "Total Gold Storage" = $GoldStorage
  "Total Silver Storage" = $SilverStorage
  "Total Storage without Policy" = $NoPolicy
  "Managed By" = $vmtag
  "DR Status" = $DRStatus
  }
 }
 
 return $list
}

#Stylesheet - this is used by the ConvertTo-html cmdlet
function header{
 $style = @"
 <style>
 body{
 font-family: Verdana, Geneva, Arial, Helvetica, sans-serif;
 }
 
 table{
  border-collapse: collapse;
  border: none;
  font: 10pt Verdana, Geneva, Arial, Helvetica, sans-serif;
  color: black;
  margin-bottom: 10px;
 }
 
 table td{
  font-size: 10px;
  padding-left: 0px;
  padding-right: 20px;
  text-align: left;
 }
 
 table th{
  font-size: 10px;
  font-weight: bold;
  padding-left: 0px;
  padding-right: 20px;
  text-align: left;
 }
 
 h2{
  clear: both; font-size: 130%;color:#00134d;
 }
 
 p{
  margin-left: 10px; font-size: 12px;
 }
 
 table.list{
  float: left;
 }
 
 table tr:nth-child(even){background: #e6f2ff;} 
 table tr:nth-child(odd) {background: #FFFFFF;}

 div.column {width: 320px; float: left;}
 div.first {padding-right: 20px; border-right: 1px grey solid;}
 div.second {margin-left: 30px;}

 table{
  margin-left: 10px;
 }
 –>
 </style>
"@

 return [string] $style
 }

#############################
### Script entry point ###
#############################

#Path to html report
 Move-Item -Path "D:\Scripts\VMReport\*.htm" -Destination "D:\Scripts\VMReport\Archive" -Force -ErrorAction Ignore
 Remove-Item -Path "D:\Scripts\VMReport\*.htm"
 $repPath= "D:\Scripts\VMReport\Report_$Date.htm"

#Report Title
 $title = "<h2>VMs hosted on $hostIP</h2>"

#Sort by
 if ($sortBy -eq "") {$sortBy="Name"; $desc=$False} 
  elseif ($sortBy.Equals("ramalloc")) {$sortBy = "RAM Alloc"; $desc=$True} 
   elseif ($sortBy.Equals("ramhost")) {$sortBy = "RAM Host"; $desc=$True} 
    elseif ($sortBy.Equals("os")) {$sortBy = "OS"; $desc=$False}

Try{
 #Drop any previously established connections
  Disconnect-VIServer -Confirm:$False -ErrorAction SilentlyContinue
 
 #Connect to vCenter or ESXi
     Connect-VIServer $hostIP -ErrorAction Stop
  
 #Get a VirtualMachine view of all vms
  $vmView = Get-View -viewtype VirtualMachine
 
 #Iterate through the view object, write the set of vm properties to a PSObject and convert the whole lot to HTML
  (vmProperties -view $vmView) | Sort-Object -Property @{Expression=$sortBy;Descending=$desc} | ConvertTo-Html -Head $(header) -PreContent $title | Set-Content -Path $repPath -ErrorAction Stop
 
 #Disconnect from vCenter or ESXi
  Disconnect-VIServer -Confirm:$False -Server $hostIP -ErrorAction Stop
 
 #Send Mail
    send-mailmessage -from $fromemail -to $users -subject "VM details Report" -Attachments $repPath -priority High -smtpServer $smtpserver
 }
Catch
 {
  Write-Host $_.Exception.Message
 }
