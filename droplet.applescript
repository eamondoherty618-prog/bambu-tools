-- Build the Dock app with:
--   osacompile -o "Optimize for X1C.app" droplet.applescript
-- Then drag a part file onto its icon.
on run
	tell application "Terminal"
		activate
		do script "clear; ~/bambu-tools/'Optimize Print.command'; exit"
	end tell
end run

on open theFiles
	set f to POSIX path of item 1 of theFiles
	tell application "Terminal"
		activate
		do script "clear; ~/bambu-tools/bambu-optimize " & quoted form of f & "; echo; echo 'Done - you can close this window.'"
	end tell
end open
