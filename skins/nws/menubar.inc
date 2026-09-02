## Copyright 2024-2026 John A Kline
## See LICENSE.txt for your rights
##
## The three pages' navigation.  Styling lives in css/nws.css, not in a
## style= attribute: the bar has to follow the reader's light/dark setting
## like everything else on the page, and an inline color cannot.
##
## $selection is set by each page before this is included.
#errorCatcher Echo
#encoding UTF-8
#set $days_class = ''
#set $hours_class = ''
#set $alerts_class = ''
#if $selection == 'days'
#set $days_class = ' class="current"'
#else if $selection == 'hours'
#set $hours_class = ' class="current"'
#else if $selection == 'alerts'
#set $alerts_class = ' class="current"'
#end if
    <nav class="nav" aria-label="Forecast pages">
      <ul>
        <li><a href="index.html"$days_class>7&nbsp;Day</a></li>
        <li><a href="hours.html"$hours_class>Hourly</a></li>
        <li><a href="alerts.html"$alerts_class>Alerts</a></li>
      </ul>
    </nav>
