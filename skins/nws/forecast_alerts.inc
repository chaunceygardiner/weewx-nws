## forecast alerts - Copyright 2020-2024 John A Kline
## See LICENSE.txt for your rights
#errorCatcher Echo
#encoding UTF-8
#import math
<div id='forecast_alerts'>
  <div>
    <table style='border-style:solid;padding:30px;border:1pt solid LightGray;'>
      #set $title_font_size = 'large'
      #set $alert_count = 0
      #for $alert in $nwsforecast.alerts()
      #set $alert_count += 1
      #set max_title_line = 80
      ## If nwsHeadline is None, use headline
      #if $alert.nwsHeadline is not None:
        #set headline = $alert.nwsHeadline
      #else
        #set headline = $alert.headline
      #end if
      #set headline_length = len($headline)
      #if $headline_length > $max_title_line
        ## Figure out how many lines.
        #set line_count = math.ceil($headline_length / float($max_title_line))
        #set max_title_line = math.ceil($headline_length / $line_count)
        #set words = $headline.split()
        #set lines = []
        #set char_count = 0
        #set idx = 0
        $lines.append("")
        #for word in $words
          #if $char_count >= $max_title_line
            #set idx += 1
            $lines.append("")
            #set char_count = 0
          #end if
          #if $lines[$idx] != ""
            #set lines[$idx] += " "
            #set char_count += 1
          #end if
          #set lines[$idx] += $word
          #set char_count += len($word)
        #end for
        #set formatted_headline = ""
        #for line in $lines
          #if $formatted_headline != ""
            #set formatted_headline += '<br>'
          #end if
          #set formatted_headline += $line
        #end for
      #else
        #set formatted_headline = $headline
      #end if
      <tr style='width:100%;'><td style='text-align:center;font-size:$title_font_size;font-weight:bold;border-bottom:1pt solid LightGray;'>$formatted_headline</td></tr>
      <tr><td style='text-align:left;'><br>Issued: $alert.effective</td></tr>
      <tr><td style='text-align:left;'>Onset: $alert.onset</td></tr>
      <tr><td style='text-align:left;'>Ends: $alert.ends</td></tr>
      <tr><td style='text-align:left;'>Status: $alert.status</td></tr>
      <tr><td style='text-align:left;'>Severity: $alert.severity</td></tr>
      <tr><td style='text-align:left;'>Certainty: $alert.certainty</td></tr>
      #try
          #set $nwsHeadline = $alert.nwsHeadline.replace('\n\n', '<br><br>')
          #set $nwsHeadline = $nwsHeadline.replace('\n', ' ')
      #except
        ## Calling replace has failed because of missing NWS Headline
        ## alert.nwsHeadline is probably None
        #set $nwsHeadline = $alert.nwsHeadline
      #end try
      #try
          #set $desc = $alert.description.replace('\n\n', '<br><br>')
          #set $desc = $desc.replace('\n', ' ')
      #except
        ## Calling replace has failed because of malformed alerts.
        ## alert.description is probably None
        #set $desc = $alert.description
      #end try
      <tr>
        <td style='text-align:left;'>
          <br>
          $nwsHeadline
        </td>
      </tr>
      <tr>
        <td style='text-align:left;'>
          <br>
          $desc
        </td>
      </tr>
      <tr>
        <td style='text-align:left;'>
          <br>
          Instructions: $alert.instructions
          <br>
          <br>
        </td>
      </tr>
      <tr><td style='text-align:left;'>ID: $alert.id</td></tr>
      <tr><td style='text-align:left;'>Headline: $alert.headline</td></tr>
      <tr><td style='text-align:left;'>Event: $alert.event</td></tr>
      <tr><td style='text-align:left;'>Expires: $alert.expires</td></tr>
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
