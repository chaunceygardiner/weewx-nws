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
      <tr><td style='text-align:left;border-top:1pt solid LightGray;'><br/>Event: $alert.event</td></tr>
      <tr><td style='text-align:left;'>Issued: $alert.effective</td></tr>
      <tr><td style='text-align:left;'>Onset: $alert.onset</td></tr>
      <tr><td style='text-align:left;border-bottom:1pt solid LightGray'>Ends: $alert.ends<br/><br/></td></tr>
      <tr style='width:100%;'><td style='text-align:center;font-size:$title_font_size;font-weight:bold;border-bottom:1pt solid LightGray;'>$alert.headline</td></tr>
      #set $desc = $alert.description.replace('\n', '<br/>')
      <tr>
        <td style='text-align:left;'>
          <br/>
          $desc
        </td>
      </tr>
      #end for
      #if $alert_count == 0
        <tr><td style='text-align:center;font-weight:bold;font-style:italic'>No active National Weather Service alerts for this location.</td></tr>
      #end if
    </table>
  </div>
</div>
