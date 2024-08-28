# 获取智能卡证书存储
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store("SmartCardRoot", "LocalMachine")
$store.Open("ReadOnly")
 
# 获取存储中的所有证书
$certificates = $store.Certificates
 
# 导出每个证书的信息
$certInfo = $certificates | ForEach-Object {
    $cert = $_
    [PSCustomObject]@{
        FriendlyName = $cert.FriendlyName
        Subject      = $cert.Subject
        Issuer       = $cert.Issuer
        NotBefore    = $cert.NotBefore
        NotAfter     = $cert.NotAfter
        HasPrivateKey= $cert.HasPrivateKey
    }
}
 
# 显示证书信息表格
$certInfo | Format-Table -AutoSize
 
# 关闭存储
$store.Close()