<?php
	//================================================== STRING ROTATE EXPANDED
	function str_shift ($string, $perc=50, $useextra=FALSE, $usedigits=TRUE, $useupper=TRUE, $uselower=TRUE) {
    static $chars = array(
        'lower' => 'abcdefghijklmnopqrstuvwxyz',
        'upper' => 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        'digits' => '0123456789',
        'extra' => ',.-()<>%/!"&=;:_[]{}#\\?\'+*',
    );
    settype($perc, 'float');
    if  (!$perc)  return $string;
    $perc = fmod((abs($perc) < 1 ? 100*$perc : $perc), 100);
    if  ($perc < 0)  $perc += 100;
    $use = (is_array($useextra) ? $useextra : array('lower'=>$uselower, 'upper'=>$useupper, 'digits'=>$usedigits, 'extra'=>$useextra));
    foreach ($chars as $type => $letters) {
        if  (!$use[$type])  continue;
        $shift = round(strlen($letters) * $perc / 100);
        $repl = substr($letters, $shift).substr($letters, 0, $shift);
        $string = strtr($string, $letters, $repl);
    }
    return $string;
}