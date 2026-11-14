<?php
namespace Acme\Notes\Model;
use Acme\Notes\Api\Data\NoteInterface;
class NoteRepository
{
    /** @param NoteInterface $note */
    public function save($note)
    {
        return $note;
    }
}
