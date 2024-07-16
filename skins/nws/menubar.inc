## Copyright 2024 John A Kline
## See LICENSE.txt for your rights
#errorCatcher Echo
#encoding UTF-8
#set days_class = ''
#set hours_class = ''
#set alerts_class = ''
#set class_attr = 'class="active"'
#if $selection == 'days'
#set days_class = $class_attr
#else if $selection == 'hours'
#set hours_class = $class_attr
#else if $selection == 'alerts'
#set alerts_class = $class_attr
#end if
    <div class="forecastnav" style="width:100%;">
      <table style="text-align:center;width:40%;margin-left:30%;">
        <tr>
          <td style="background-color:black;text-align:center;">
            <a href="." style="width:33%;" $days_class>7 Day</a>
            <a href="hours.html" style="width:34%;" $hours_class>Hourly</a>
            <a href="alerts.html" style="width:33%;" $alerts_class>Alerts</a>
          </td>
        </tr>
      </table>
    </div>
