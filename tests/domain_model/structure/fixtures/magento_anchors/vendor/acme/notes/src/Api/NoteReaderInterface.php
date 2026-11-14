<?php
namespace Vendor\Notes\Api;
use Acme\Notes\Api\Data\NoteInterface;
interface NoteReaderInterface
{
    public function get(NoteInterface $note);
}
