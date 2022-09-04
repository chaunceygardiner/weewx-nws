## forecast days - Copyright 2020 John A Kline
## See LICENSE.txt for your rights
#errorCatcher Echo
#encoding UTF-8
<div id='forecast_alerts'>
  <div>
    <table style='border-style:solid;padding:30px;border:1pt solid LightGray;'>
      #set $title_font_size = 'large'
      #set $alert_count = 0
      #for $alert in $nwsforecast.alerts()
      #set $alert_count += 1
      <tr style='width:100%;'><td style='text-align:center;font-size:$title_font_size;font-weight:bold;border-bottom:1pt solid LightGray;'>$alert.headline</td></tr>
      <tr><td style='text-align:left;'><br/>Status: $alert.status</td></tr>
      <tr><td style='text-align:left;'>Severity: $alert.severity</td></tr>
      <tr><td style='text-align:left;'>Certainty: $alert.certainty</td></tr>
      #set $desc = $alert.description.replace('\n', '<br/>')
      <tr>
        <td style='text-align:left;'>
          <br/>
          $desc
        </td>
      </tr>
      <tr>
        <td style='text-align:left;'>
          <br/>
          Instructions: $alert.instructions
          <br/>
          <br/>
        </td>
      </tr>
      <tr><td style='text-align:left;'>ID: $alert.id</td></tr>
      <tr><td style='text-align:left;'>Event: $alert.event</td></tr>
      <tr><td style='text-align:left;'>Issued: $alert.effective</td></tr>
      <tr><td style='text-align:left;'>Expires: $alert.expires</td></tr>
      <tr><td style='text-align:left;'>Onset: $alert.onset</td></tr>
      <tr><td style='text-align:left;'>Ends: $alert.ends</td></tr>
      <tr><td style='text-align:left;'>Sent: $alert.sent</td></tr>
      <tr><td style='text-align:left;'>Message Type: $alert.messageType</td></tr>
      <tr><td style='text-align:left;'>Category: $alert.category</td></tr>
      <tr><td style='text-align:left;'>Urgency: $alert.urgency</td></tr>
      <tr><td style='text-align:left;'>Sender: $alert.sender</td></tr>
      <tr><td style='text-align:left;'>Sender Name: $alert.senderName</td></tr>
      #end for
      #if $alert_count == 0
        <tr><td style='text-align:center;font-weight:bold;font-style:italic'>No active National Weather Service alerts for this location.</td></tr>
      #end if
    </table>
  </div>
</div>
